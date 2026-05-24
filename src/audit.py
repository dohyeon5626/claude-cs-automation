"""
Audit logger — appends one JSON line per CS question to ./log/queries.jsonl.

Each event captures the question, the SQL queries that ran, timings, and
the outcome, so the operator can later count traffic and trace what was
asked. Failures here never block a query: any IO error is swallowed.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_LOG_DIR = Path("log")
_LOG_FILE = _LOG_DIR / "queries.jsonl"
_LOCK = threading.Lock()


def now_iso() -> str:
    """Local-timezone ISO 8601 timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log_query_event(entry: Dict[str, Any]) -> None:
    """Append one event to log/queries.jsonl. Best-effort: never raises."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _LOCK:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
