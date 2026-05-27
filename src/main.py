import logging
import socket
import sys
from typing import Dict, Optional

from aiohttp import web

from .agent import (
    ClaudeAgent,
    check_claude_cli_authenticated,
    check_claude_cli_installed,
)
from .auth import Authenticator
from .config import AppConfig, load_config
from .database import Database, create_database
from .repository import check_git_config, sync_repo
from .server import WebServer
from .service import Service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _fail(message: str):
    print("실패")
    print(f"\n오류: {message}")
    sys.exit(1)


def _get_lan_ip() -> str:
    """
    Return the LAN IP that other devices on the same network would use
    to reach this machine. Picks a route without actually sending packets.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def run_startup_checks(config: AppConfig) -> Dict[str, Service]:
    """
    Validate the environment and every service. Returns the runtime
    service map on success; exits the process on any failure.
    """
    print("=" * 60)
    print("  CS Automation - 시작 검증")
    print("=" * 60)

    print("\n[공통] Git 설정 확인...", end=" ", flush=True)
    try:
        check_git_config()
        print("OK")
    except RuntimeError as e:
        _fail(str(e))

    print("[공통] Claude CLI 설치 확인...", end=" ", flush=True)
    try:
        check_claude_cli_installed(config.claude_binary)
        print("OK")
    except RuntimeError as e:
        _fail(str(e))

    print("[공통] Claude CLI 로그인 확인...", end=" ", flush=True)
    logged_in, detail = check_claude_cli_authenticated(
        config.claude_model, config.claude_binary
    )
    if logged_in:
        print("OK")
    else:
        # Soft failure — server still starts. Admins can log in from the
        # web UI's header button once it's up.
        print("로그아웃 상태")
        print(f"   ↳ {detail}")
        print("   ↳ 서버는 계속 실행됩니다. 웹에서 관리자 계정으로 접속해")
        print("     헤더의 'Claude 로그인' 버튼을 눌러 로그인하세요.")

    services: Dict[str, Service] = {}
    for svc in config.services:
        print(f"\n[서비스] {svc.id} ({svc.name})")

        print("  - GitHub 레포 동기화...", end=" ", flush=True)
        try:
            sync_repo(svc.github, svc.repo_path)
            print("OK")
        except RuntimeError as e:
            _fail(str(e))

        database: Optional[Database] = None
        if svc.database is None:
            print("  - 데이터베이스 없음 (레포만 사용)")
        else:
            print(f"  - 데이터베이스 연결 ({svc.database.kind})...", end=" ", flush=True)
            try:
                database = create_database(svc.database)
                print("OK")
            except RuntimeError as e:
                _fail(str(e))

            print("  - 스키마 분석...", end=" ", flush=True)
            try:
                database.get_schema()
                print("OK")
            except RuntimeError as e:
                _fail(str(e))

        services[svc.id] = Service(config=svc, database=database)

    print("\n모든 검증을 통과했습니다.\n")
    return services


def main():
    try:
        config = load_config("config.yml")
    except (FileNotFoundError, ValueError) as e:
        print(f"설정 오류: {e}")
        sys.exit(1)

    services = run_startup_checks(config)

    auth = Authenticator(config.users, config.services)
    agent = ClaudeAgent(model=config.claude_model, binary=config.claude_binary)
    server = WebServer(config=config, agent=agent, auth=auth, services=services)

    port = config.port
    lan_ip = _get_lan_ip()
    print("CS 담당자는 아래 주소로 웹 브라우저에서 접속하세요:")
    print(f"  - 이 PC에서:           http://localhost:{port}")
    print(f"  - 같은 WiFi의 다른 PC: http://{lan_ip}:{port}")
    print(f"\n사용자 {len(config.users)}명 · 서비스 {len(config.services)}개 로드됨.")
    print("종료하려면 Ctrl+C 를 누르세요.\n")

    web.run_app(
        server.build_app(),
        host="0.0.0.0",
        port=port,
        print=lambda *args: None,
    )


if __name__ == "__main__":
    main()
