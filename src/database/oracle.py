"""Oracle adapter — uses python-oracledb (thin mode, no Oracle client needed)."""

import re
from typing import Any, Dict, List

try:
    import oracledb
except ImportError as e:
    raise RuntimeError(
        "Oracle 드라이버가 없습니다.\n"
        "  설치: pip install -r requirements-oracle.txt\n"
        "  또는: pip install 'oracledb>=2.0'"
    ) from e

from .base import (
    Database,
    _DEFAULT_LIMIT,
    _MAX_AGG_LIMIT,
    _MAX_LIMIT,
    _QUERY_TIMEOUT_MS,
    _is_aggregation_query,
)


# `FETCH FIRST N ROWS ONLY` or `FETCH NEXT N ROWS ONLY` (Oracle 12c+)
_FETCH_RE = re.compile(
    r"\bFETCH\s+(?:FIRST|NEXT)\s+(\d+)\s+ROWS?\s+ONLY\b",
    re.IGNORECASE,
)


class OracleDatabase(Database):
    dialect = "oracle"

    def _connect(self):
        # Service-name style DSN; works in oracledb thin mode without an
        # Oracle Instant Client install. Use `host:port/service_name`.
        dsn = f"{self._config.host}:{self._config.port}/{self._config.name}"
        conn = oracledb.connect(
            user=self._config.user,
            password=self._config.password,
            dsn=dsn,
        )
        # Oracle wraps statement-level timeout at the connection level
        # (in milliseconds). Setting it here covers the cursor.execute below.
        try:
            conn.call_timeout = _QUERY_TIMEOUT_MS
        except Exception:
            pass
        return conn

    def cap_limit(self, sql: str) -> str:
        """
        Oracle uses `FETCH FIRST N ROWS ONLY` instead of LIMIT. Cap or
        inject accordingly. Aggregation queries are exempted from the
        auto-inject (same policy as the MySQL/PG path).
        """
        max_limit = _MAX_AGG_LIMIT if _is_aggregation_query(sql) else _MAX_LIMIT
        m = _FETCH_RE.search(sql)
        if not m:
            if max_limit == _MAX_AGG_LIMIT:
                return sql
            return sql.rstrip(";") + f" FETCH FIRST {_DEFAULT_LIMIT} ROWS ONLY"
        n = int(m.group(1))
        if n > max_limit:
            return _FETCH_RE.sub(f"FETCH FIRST {max_limit} ROWS ONLY", sql, count=1)
        return sql

    def _format_error(self, e: Exception) -> str:
        msg = str(e)
        lower = msg.lower()
        if "dpy-4011" in lower or "call timeout" in lower or "ora-01013" in lower:
            return (
                f"쿼리가 {_QUERY_TIMEOUT_MS // 1000}초를 초과해 중단되었습니다. "
                "조건을 더 좁히거나 쿼리를 단순화해 주세요."
            )
        return f"쿼리 실행 실패: {msg}"

    def get_schema(self) -> str:
        """
        Read tables/columns from Oracle catalog (USER_* views — current
        schema only, what the configured user owns).
        """
        conn = self._connect()
        cursor = None
        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT TABLE_NAME, COMMENTS FROM USER_TAB_COMMENTS"
            )
            table_comments = {row[0]: (row[1] or "").strip() for row in cursor.fetchall()}

            cursor.execute(
                """
                SELECT col.TABLE_NAME,
                       col.COLUMN_NAME,
                       col.DATA_TYPE
                         || CASE WHEN col.DATA_TYPE IN ('VARCHAR2','CHAR','NVARCHAR2','NCHAR')
                                 THEN '(' || col.CHAR_LENGTH || ')'
                                 WHEN col.DATA_TYPE = 'NUMBER' AND col.DATA_PRECISION IS NOT NULL
                                 THEN '(' || col.DATA_PRECISION
                                      || NVL2(col.DATA_SCALE, ',' || col.DATA_SCALE, '')
                                      || ')'
                                 ELSE ''
                            END                                              AS COLUMN_TYPE,
                       col.NULLABLE,
                       CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'PRI' ELSE '' END AS COLUMN_KEY,
                       COALESCE(cc.COMMENTS, '')                              AS COLUMN_COMMENT
                FROM USER_TAB_COLUMNS col
                LEFT JOIN USER_COL_COMMENTS cc
                       ON cc.TABLE_NAME = col.TABLE_NAME
                      AND cc.COLUMN_NAME = col.COLUMN_NAME
                LEFT JOIN (
                    SELECT acc.TABLE_NAME, acc.COLUMN_NAME
                    FROM USER_CONSTRAINTS uc
                    JOIN USER_CONS_COLUMNS acc
                      ON acc.CONSTRAINT_NAME = uc.CONSTRAINT_NAME
                    WHERE uc.CONSTRAINT_TYPE = 'P'
                ) pk ON pk.TABLE_NAME = col.TABLE_NAME
                    AND pk.COLUMN_NAME = col.COLUMN_NAME
                ORDER BY col.TABLE_NAME, col.COLUMN_ID
                """
            )
            columns = cursor.fetchall()
        except oracledb.Error as e:
            raise RuntimeError(f"스키마 분석 실패: {e}")
        finally:
            if cursor is not None:
                cursor.close()
            conn.close()

        tables: Dict[str, List[tuple]] = {}
        for col in columns:
            tables.setdefault(col[0], []).append(col)

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
                _, col_name, col_type, nullable_flag, column_key, col_comment = c
                key = " [PK]" if column_key == "PRI" else ""
                nullable = "" if nullable_flag == "Y" else " NOT NULL"
                ccomment = f"  -- {col_comment}" if (col_comment or "").strip() else ""
                lines.append(f"- {col_name}: {col_type}{key}{nullable}{ccomment}")
            parts.append("\n".join(lines))

        return f"테이블 {len(tables)}개\n\n" + "\n\n".join(parts)
