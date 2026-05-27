"""PostgreSQL adapter — uses psycopg2-binary."""

from typing import Any, Dict, List

try:
    import psycopg2
    from psycopg2 import Error as _DriverError
except ImportError as e:
    raise RuntimeError(
        "PostgreSQL 드라이버가 없습니다.\n"
        "  설치: pip install -r requirements-postgres.txt\n"
        "  또는: pip install 'psycopg2-binary>=2.9'"
    ) from e

from .base import Database, _QUERY_TIMEOUT_MS


class PostgresDatabase(Database):
    dialect = "postgres"

    def _connect(self):
        return psycopg2.connect(
            host=self._config.host,
            port=self._config.port,
            dbname=self._config.name,
            user=self._config.user,
            password=self._config.password,
            connect_timeout=10,
        )

    def _apply_timeout(self, conn, cursor):
        # PostgreSQL's statement_timeout is in milliseconds
        cursor.execute(f"SET statement_timeout = {_QUERY_TIMEOUT_MS}")

    def _format_error(self, e: Exception) -> str:
        msg = str(e).lower()
        if "statement timeout" in msg or "canceling statement" in msg or "due to user request" in msg:
            return (
                f"쿼리가 {_QUERY_TIMEOUT_MS // 1000}초를 초과해 중단되었습니다. "
                "조건을 더 좁히거나 쿼리를 단순화해 주세요."
            )
        return f"쿼리 실행 실패: {e}"

    def get_schema(self) -> str:
        """
        Read tables/columns from PostgreSQL catalog. Limits to user-visible
        tables (excludes pg_catalog and information_schema).
        """
        conn = self._connect()
        cursor = None
        try:
            cursor = conn.cursor()

            # Table comments via pg_description
            cursor.execute(
                """
                SELECT c.relname AS table_name,
                       COALESCE(obj_description(c.oid, 'pg_class'), '') AS table_comment
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p', 'v', 'm')
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'
                """
            )
            table_comments = {row[0]: (row[1] or "").strip() for row in cursor.fetchall()}

            # Columns + types + primary-key hint + comments
            cursor.execute(
                """
                SELECT  c.table_name,
                        c.column_name,
                        c.data_type,
                        c.is_nullable,
                        CASE WHEN pk.column_name IS NOT NULL THEN 'PRI' ELSE '' END AS column_key,
                        COALESCE(col_description(pg.oid, c.ordinal_position::int), '') AS column_comment
                FROM information_schema.columns c
                JOIN pg_class pg ON pg.relname = c.table_name
                JOIN pg_namespace n ON n.oid = pg.relnamespace AND n.nspname = c.table_schema
                LEFT JOIN (
                    SELECT kcu.table_schema, kcu.table_name, kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON kcu.constraint_name = tc.constraint_name
                     AND kcu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                ) pk ON pk.table_schema = c.table_schema
                    AND pk.table_name = c.table_name
                    AND pk.column_name = c.column_name
                WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND c.table_schema NOT LIKE 'pg_toast%'
                ORDER BY c.table_name, c.ordinal_position
                """
            )
            columns = cursor.fetchall()
        except _DriverError as e:
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
                _, col_name, data_type, is_nullable, column_key, col_comment = c
                key = " [PK]" if column_key == "PRI" else ""
                nullable = "" if is_nullable == "YES" else " NOT NULL"
                ccomment = f"  -- {col_comment}" if (col_comment or "").strip() else ""
                lines.append(f"- {col_name}: {data_type}{key}{nullable}{ccomment}")
            parts.append("\n".join(lines))

        return f"테이블 {len(tables)}개\n\n" + "\n\n".join(parts)
