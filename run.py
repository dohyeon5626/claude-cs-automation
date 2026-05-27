"""
Entry point. Handles venv + dependency bootstrap before starting the server.

First run on a fresh checkout:
  python run.py        ← creates .venv, installs core + needed DB drivers, starts server

Subsequent runs:
  python run.py        ← skips installed deps (~0.5s overhead), starts server

The script reads config.yml to discover which DB engines are used and
only installs the matching requirements-<kind>.txt for them. If you're
already inside any venv (yours or another tool's), it reuses that one
instead of creating .venv.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)

VENV_DIR = PROJECT_ROOT / ".venv"
VENV_PY = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _in_any_venv() -> bool:
    """True if we're already running under any venv/virtualenv."""
    return sys.prefix != sys.base_prefix


def _ensure_venv_and_reexec():
    """If not in a venv, create .venv and re-exec ourselves under it."""
    if _in_any_venv():
        return
    if not VENV_DIR.exists():
        print("가상환경 .venv 를 생성합니다 (최초 1회)...")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        except subprocess.CalledProcessError as e:
            print(f"오류: venv 생성 실패: {e}")
            sys.exit(1)
    print(f"가상환경 .venv 로 재실행합니다...")
    os.execv(str(VENV_PY), [str(VENV_PY), __file__, *sys.argv[1:]])


def _pip_install(*args):
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install",
         "-q", "--disable-pip-version-check", *args]
    )


def _install_core_deps():
    """Skip pip if core packages already import cleanly."""
    try:
        import aiohttp  # noqa: F401
        import openpyxl  # noqa: F401
        import yaml  # noqa: F401
        return
    except ImportError:
        pass
    print("공통 의존성을 설치합니다...")
    _pip_install("-r", "requirements.txt")


def _driver_installed(kind: str) -> bool:
    try:
        if kind == "mysql":
            import mysql.connector  # noqa: F401
        elif kind == "postgres":
            import psycopg2  # noqa: F401
        elif kind == "oracle":
            import oracledb  # noqa: F401
        else:
            return True  # unknown kind → let main.py raise a clear error
        return True
    except ImportError:
        return False


def _install_db_drivers():
    """
    Peek at config.yml, collect every database.kind in use, install the
    matching requirements-<kind>.txt for any that aren't importable yet.
    """
    import yaml  # PyYAML is in core, just installed above

    config_path = Path("config.yml")
    if not config_path.exists():
        return  # main.py will surface "config.yml 없음" with proper context

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        print(f"  ⚠ config.yml 파싱 오류: {e}")
        print("  ⚠ DB 드라이버 자동 설치를 건너뜁니다.")
        return

    kinds = set()
    for s in raw.get("services") or []:
        db = s.get("database") if isinstance(s, dict) else None
        if not db:
            continue
        k = str(db.get("kind", "mysql") or "mysql").lower().strip()
        if k in ("postgresql", "pg"):
            k = "postgres"
        kinds.add(k)

    for kind in sorted(kinds):
        if _driver_installed(kind):
            continue
        req = PROJECT_ROOT / f"requirements-{kind}.txt"
        if not req.exists():
            continue
        print(f"{kind} 드라이버를 설치합니다...")
        _pip_install("-r", str(req))


def main():
    _ensure_venv_and_reexec()  # may exec — anything below runs in the venv
    _install_core_deps()
    _install_db_drivers()
    from src.main import main as run_main
    run_main()


if __name__ == "__main__":
    main()
