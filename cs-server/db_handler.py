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
