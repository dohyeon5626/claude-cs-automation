"""MySQL adapter — uses mysql-connector-python."""

from typing import Any, Dict, List

try:
    import mysql.connector
    from mysql.connector import Error as _DriverError
except ImportError as e:
    raise RuntimeError(
        "MySQL 드라이버가 없습니다.\n"
        "  설치: pip install -r requirements-mysql.txt\n"
        "  또는: pip install 'mysql-connector-python>=8.0'"
    ) from e

from .base import Database, _QUERY_TIMEOUT_MS


class MySQLDatabase(Database):
    dialect = "mysql"

    def _connect(self):
        return mysql.connector.connect(
            host=self._config.host,
            port=self._config.port,
            database=self._config.name,
            user=self._config.user,
            password=self._config.password,
            charset="utf8mb4",
            use_unicode=True,
            connection_timeout=10,
        )

    def _apply_timeout(self, conn, cursor):
        try:
            cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {_QUERY_TIMEOUT_MS}")
        except _DriverError:
            pass  # MySQL < 5.7.8 — silently fall back

    def _format_error(self, e: Exception) -> str:
        msg = str(e).lower()
        if "max_execution_time" in msg or "interrupted" in msg or "exceeded" in msg:
            return (
                f"쿼리가 {_QUERY_TIMEOUT_MS // 1000}초를 초과해 중단되었습니다. "
                "조건을 더 좁히거나 쿼리를 단순화해 주세요."
            )
        return f"쿼리 실행 실패: {e}"

    def get_schema(self) -> str:
        conn = self._connect()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "SELECT TABLE_NAME, TABLE_COMMENT "
                "FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = %s",
                (self._config.name,),
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
                (self._config.name,),
            )
            columns = cursor.fetchall()
        except _DriverError as e:
            raise RuntimeError(f"스키마 분석 실패: {e}")
        finally:
            if cursor is not None:
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
