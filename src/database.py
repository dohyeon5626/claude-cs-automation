import re
from typing import Any, Dict, List

import mysql.connector
from mysql.connector import Error as MySQLError

from .config import DatabaseConfig

# Cost-control caps for runaway queries
_DEFAULT_LIMIT = 100        # auto-appended when a query has no LIMIT
_MAX_LIMIT = 1000           # hard cap on any LIMIT value
_QUERY_TIMEOUT_MS = 30_000  # 30s per-statement timeout (MySQL 5.7.8+)


class Database:
    """A connection to one service's MySQL database (read-only use)."""

    def __init__(self, config: DatabaseConfig):
        self._params = {
            "host": config.host,
            "port": config.port,
            "database": config.name,
            "user": config.user,
            "password": config.password,
            "charset": "utf8mb4",
            "use_unicode": True,
            "connection_timeout": 10,
        }
        self._name = config.name
        self._test_connection()

    def _test_connection(self):
        try:
            conn = mysql.connector.connect(**self._params)
            conn.close()
        except MySQLError as e:
            raise RuntimeError(f"데이터베이스 연결 실패: {e}")

    def execute_select(self, query: str) -> List[Dict[str, Any]]:
        """
        Run a SELECT query and return rows as a list of dicts.
        Rejects any non-SELECT query, caps LIMIT at _MAX_LIMIT,
        and enforces a per-statement timeout.
        """
        clean = query.strip()

        if not re.match(r"^\s*SELECT\b", clean, re.IGNORECASE):
            raise ValueError(
                f"보안: SELECT 쿼리만 허용됩니다. 받은 쿼리: {clean[:60]}..."
            )

        clean = _cap_limit(clean)

        conn = mysql.connector.connect(**self._params)
        try:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {_QUERY_TIMEOUT_MS}")
            except MySQLError:
                pass  # MySQL < 5.7.8 or non-MySQL — silently fall back
            cursor.execute(clean)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except MySQLError as e:
            raise RuntimeError(_format_query_error(e))
        finally:
            cursor.close()
            conn.close()

    def get_schema(self) -> str:
        """Read the live table/column structure from INFORMATION_SCHEMA."""
        conn = mysql.connector.connect(**self._params)
        try:
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "SELECT TABLE_NAME, TABLE_COMMENT "
                "FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = %s",
                (self._name,),
            )
            table_comments = {
                r["TABLE_NAME"]: (r["TABLE_COMMENT"] or "").strip()
                for r in cursor.fetchall()
            }

            cursor.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, "
                "COLUMN_KEY, COLUMN_COMMENT "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s "
                "ORDER BY TABLE_NAME, ORDINAL_POSITION",
                (self._name,),
            )
            columns = cursor.fetchall()
        except MySQLError as e:
            raise RuntimeError(f"스키마 분석 실패: {e}")
        finally:
            cursor.close()
            conn.close()

        tables: Dict[str, List[Dict[str, Any]]] = {}
        for col in columns:
            tables.setdefault(col["TABLE_NAME"], []).append(col)

        if not tables:
            return "데이터베이스에 테이블이 없습니다."

        parts = []
        for table_name, cols in tables.items():
            comment = table_comments.get(table_name, "")
            header = f"### {table_name}"
            if comment:
                header += f"  -- {comment}"
            lines = [header]
            for c in cols:
                key = ""
                if c["COLUMN_KEY"] == "PRI":
                    key = " [PK]"
                elif c["COLUMN_KEY"] == "MUL":
                    key = " [INDEX]"
                nullable = "" if c["IS_NULLABLE"] == "YES" else " NOT NULL"
                ccomment = (
                    f"  -- {c['COLUMN_COMMENT']}"
                    if (c["COLUMN_COMMENT"] or "").strip()
                    else ""
                )
                lines.append(
                    f"- {c['COLUMN_NAME']}: {c['COLUMN_TYPE']}{key}{nullable}{ccomment}"
                )
            parts.append("\n".join(lines))

        return f"테이블 {len(tables)}개\n\n" + "\n\n".join(parts)


# ── Query-cost helpers ─────────────────────────────────────────────────────

_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?", re.IGNORECASE)


def _cap_limit(sql: str) -> str:
    """
    Ensure the query has a LIMIT no greater than _MAX_LIMIT.
      - No LIMIT at all       → append "LIMIT _DEFAULT_LIMIT"
      - LIMIT N               → if N > _MAX_LIMIT, rewrite to _MAX_LIMIT
      - LIMIT offset, count   → if count > _MAX_LIMIT, rewrite count to _MAX_LIMIT
    """
    m = _LIMIT_RE.search(sql)
    if not m:
        return sql.rstrip(";") + f" LIMIT {_DEFAULT_LIMIT}"

    if m.group(2) is not None:
        offset, count = int(m.group(1)), int(m.group(2))
        if count > _MAX_LIMIT:
            return _LIMIT_RE.sub(f"LIMIT {offset}, {_MAX_LIMIT}", sql, count=1)
    else:
        n = int(m.group(1))
        if n > _MAX_LIMIT:
            return _LIMIT_RE.sub(f"LIMIT {_MAX_LIMIT}", sql, count=1)

    return sql


def _format_query_error(e: MySQLError) -> str:
    msg = str(e).lower()
    if "max_execution_time" in msg or "interrupted" in msg or "exceeded" in msg:
        return (
            f"쿼리가 {_QUERY_TIMEOUT_MS // 1000}초를 초과해 중단되었습니다. "
            f"조건을 더 좁히거나 쿼리를 단순화해 주세요."
        )
    return f"쿼리 실행 실패: {e}"
