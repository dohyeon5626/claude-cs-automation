"""
Shared base class + helpers for all database adapters.

Each engine module subclasses Database and overrides the engine-specific
hooks (_connect, _apply_timeout, get_schema, cap_limit, _format_error).
The SELECT-only check, the byte-streaming fetch loop, and the byte cap
all live in execute_select on the base class so behavior is identical
across MySQL / PostgreSQL / Oracle.
"""

import re
from typing import Any, Dict, List

from ..config import DatabaseConfig

# Cost-control caps for runaway queries
_DEFAULT_LIMIT = 100              # auto-appended when a plain SELECT has no LIMIT
_MAX_LIMIT = 1000                 # hard cap on plain SELECTs (raw row dumps)
_MAX_AGG_LIMIT = 10_000           # higher cap for aggregation/statistics queries
_QUERY_TIMEOUT_MS = 30_000        # 30s per-statement timeout
_MAX_RESULT_BYTES = 5 * 1024 * 1024  # 5MB hard cap, even mid-fetch
_FETCH_BATCH = 500                # rows per fetchmany batch during streaming

_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?", re.IGNORECASE)
_AGG_FUNC_RE = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)


class Database:
    """
    Abstract base for an engine-specific read-only database adapter.

    Subclasses MUST implement: _connect, get_schema.
    Subclasses MAY override: _apply_timeout, cap_limit, _format_error.
    """

    # ──────────────────────────────────────────────────────────────────
    # Subclass should set this so prompts can mention the right syntax
    # ("LIMIT N" for mysql/postgres, "FETCH FIRST N ROWS ONLY" for oracle).
    dialect: str = "sql"

    def __init__(self, config: DatabaseConfig):
        self._config = config
        self._test_connection()

    def _test_connection(self):
        try:
            conn = self._connect()
            conn.close()
        except Exception as e:
            raise RuntimeError(f"데이터베이스 연결 실패: {e}")

    # ── To override per engine ────────────────────────────────────────

    def _connect(self):
        """Return a fresh DB-API-style connection object. Required."""
        raise NotImplementedError

    def _apply_timeout(self, conn, cursor):
        """Set the per-statement timeout. Default = no-op."""
        pass

    def cap_limit(self, sql: str) -> str:
        """
        Inject / cap a LIMIT clause on a plain SELECT.
        Default implementation uses the standard 'LIMIT N' clause
        (MySQL, PostgreSQL, SQLite). Oracle overrides this.
        """
        max_limit = _MAX_AGG_LIMIT if _is_aggregation_query(sql) else _MAX_LIMIT
        m = _LIMIT_RE.search(sql)
        if not m:
            if max_limit == _MAX_AGG_LIMIT:
                return sql  # don't force a LIMIT on aggregations
            return sql.rstrip(";") + f" LIMIT {_DEFAULT_LIMIT}"
        if m.group(2) is not None:
            offset, count = int(m.group(1)), int(m.group(2))
            if count > max_limit:
                return _LIMIT_RE.sub(f"LIMIT {offset}, {max_limit}", sql, count=1)
        else:
            n = int(m.group(1))
            if n > max_limit:
                return _LIMIT_RE.sub(f"LIMIT {max_limit}", sql, count=1)
        return sql

    def _format_error(self, e: Exception) -> str:
        msg = str(e).lower()
        if "timeout" in msg or "exceeded" in msg or "interrupted" in msg or "canceling" in msg:
            return (
                f"쿼리가 {_QUERY_TIMEOUT_MS // 1000}초를 초과해 중단되었습니다. "
                "조건을 더 좁히거나 쿼리를 단순화해 주세요."
            )
        return f"쿼리 실행 실패: {e}"

    def get_schema(self) -> str:
        """Engine-specific catalog dump. Required."""
        raise NotImplementedError

    # ── Shared execution workflow ─────────────────────────────────────

    def execute_select(self, query: str) -> List[Dict[str, Any]]:
        """
        Run a SELECT query and return rows as a list of dicts.
        Rejects any non-SELECT, caps LIMIT via dialect-specific cap_limit,
        applies the statement timeout, and streams rows with a 5MB byte cap
        so a single huge-BLOB row can't blow up memory.
        """
        clean = query.strip()
        if not re.match(r"^\s*SELECT\b", clean, re.IGNORECASE):
            raise ValueError(
                f"보안: SELECT 쿼리만 허용됩니다. 받은 쿼리: {clean[:60]}..."
            )

        clean = self.cap_limit(clean)

        conn = self._connect()
        cursor = None
        try:
            cursor = conn.cursor()
            try:
                self._apply_timeout(conn, cursor)
            except Exception:
                pass  # best-effort; missing privilege shouldn't break the query
            cursor.execute(clean)

            columns = [d[0] for d in cursor.description] if cursor.description else []

            rows: List[Dict[str, Any]] = []
            total_bytes = 0
            while True:
                batch = cursor.fetchmany(_FETCH_BATCH)
                if not batch:
                    break
                for row in batch:
                    row_dict = dict(row) if isinstance(row, dict) else dict(zip(columns, row))
                    rows.append(row_dict)
                    total_bytes += _estimate_row_bytes(row_dict)
                    if total_bytes > _MAX_RESULT_BYTES:
                        raise RuntimeError(
                            f"결과가 {_MAX_RESULT_BYTES // (1024 * 1024)}MB "
                            f"한도를 초과해 중단했습니다 ({len(rows)}행까지 읽음). "
                            "조건을 좁히거나 통계 쿼리(COUNT/SUM/GROUP BY)로 바꿔 주세요."
                        )
            return rows
        except Exception as e:
            if isinstance(e, (ValueError, RuntimeError)):
                raise
            raise RuntimeError(self._format_error(e))
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass


# ── Shared helpers ────────────────────────────────────────────────────────

def _is_aggregation_query(sql: str) -> bool:
    """COUNT/SUM/AVG/MIN/MAX or GROUP BY → number of groups bounds output."""
    return bool(_AGG_FUNC_RE.search(sql)) or bool(_GROUP_BY_RE.search(sql))


def _estimate_row_bytes(row: Dict[str, Any]) -> int:
    """Cheap upper-bound estimate of a row's serialized size."""
    n = 32
    for k, v in row.items():
        n += len(k) + 6
        if v is None:
            n += 4
        elif isinstance(v, (int, float, bool)):
            n += 12
        elif isinstance(v, (bytes, bytearray)):
            n += len(v)
        else:
            n += len(str(v))
    return n
