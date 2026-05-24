"""
Audit logger — appends one JSON line per CS question to log/queries.jsonl
and keeps a rolling daily-totals file at log/stats.json.

Each event captures the question, the SQL queries that ran, timings, and
the outcome, so the operator can later count traffic and trace what was
asked. Failures here never block a query: any IO error is swallowed.
"""

import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict

_LOG_DIR = Path("log")
_LOG_FILE = _LOG_DIR / "queries.jsonl"
_STATS_FILE = _LOG_DIR / "stats.json"
_LOCK = threading.Lock()


def now_iso() -> str:
    """Local-timezone ISO 8601 timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log_query_event(entry: Dict[str, Any]) -> None:
    """
    Append one event to log/queries.jsonl AND update the daily totals in
    log/stats.json. Best-effort: never raises.
    """
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _LOCK:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            _update_stats_locked(entry)
    except Exception:
        pass


def _update_stats_locked(entry: Dict[str, Any]) -> None:
    """Read-modify-write the daily stats file. Caller must hold _LOCK."""
    today = date.today().isoformat()  # local-tz YYYY-MM-DD
    service = entry.get("service", "unknown")
    answered = bool(entry.get("answered", False))

    try:
        if _STATS_FILE.exists():
            with open(_STATS_FILE, "r", encoding="utf-8") as f:
                stats: Dict[str, Any] = json.load(f)
        else:
            stats = {}
    except Exception:
        stats = {}  # corrupt or unreadable — start fresh

    day = stats.setdefault(
        today,
        {"total": 0, "answered": 0, "failed": 0, "by_service": {}},
    )
    day["total"] += 1
    day["answered" if answered else "failed"] += 1
    day["by_service"][service] = day["by_service"].get(service, 0) + 1

    # Atomic write: tmp + rename so a crash mid-write can't corrupt stats.json
    tmp = _STATS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    tmp.replace(_STATS_FILE)
