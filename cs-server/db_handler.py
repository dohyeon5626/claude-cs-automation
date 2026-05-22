import re
from typing import Any, Dict, List

import mysql.connector
from mysql.connector import Error as MySQLError


class DatabaseHandler:
    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self._config = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "charset": "utf8mb4",
            "use_unicode": True,
            "connection_timeout": 10,
        }
        self._test_connection()

    def _test_connection(self):
        try:
            conn = mysql.connector.connect(**self._config)
            conn.close()
        except MySQLError as e:
            raise RuntimeError(
                f"Database connection failed: {e}\n"
                "  Check your config.yml [database] settings."
            )

    def execute_select(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return rows as list of dicts.
        Rejects non-SELECT queries and adds LIMIT 100 if missing for safety.
        """
        clean = query.strip()

        if not re.match(r"^\s*SELECT\b", clean, re.IGNORECASE):
            raise ValueError(
                f"Security: only SELECT queries are permitted, got: {clean[:60]}..."
            )

        if not re.search(r"\bLIMIT\b", clean, re.IGNORECASE):
            clean = clean.rstrip(";") + " LIMIT 100"

        conn = mysql.connector.connect(**self._config)
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(clean)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except MySQLError as e:
            raise RuntimeError(f"Query execution failed: {e}")
        finally:
            cursor.close()
            conn.close()

    def get_schema_introspection(self) -> str:
        """
        Read the live table/column structure from INFORMATION_SCHEMA.
        Returns a Markdown-formatted description for use as Claude's context.
        """
        db_name = self._config["database"]
        conn = mysql.connector.connect(**self._config)
        try:
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "SELECT TABLE_NAME, TABLE_COMMENT "
                "FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = %s",
                (db_name,),
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
                (db_name,),
            )
            columns = cursor.fetchall()
        except MySQLError as e:
            raise RuntimeError(f"Schema introspection failed: {e}")
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
                    f"  -- {c['COLUMN_COMMENT']}" if (c["COLUMN_COMMENT"] or "").strip() else ""
                )
                lines.append(
                    f"- {c['COLUMN_NAME']}: {c['COLUMN_TYPE']}{key}{nullable}{ccomment}"
                )
            parts.append("\n".join(lines))

        return f"테이블 {len(tables)}개\n\n" + "\n\n".join(parts)
