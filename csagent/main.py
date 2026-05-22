import logging
import sys
from typing import Dict

from aiohttp import web

from .agent import ClaudeAgent, check_claude_cli
from .auth import Authenticator
from .config import AppConfig, load_config
from .database import Database
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

    print("[공통] Claude CLI 확인...", end=" ", flush=True)
    try:
        check_claude_cli(config.claude_model)
        print("OK")
    except RuntimeError as e:
        _fail(str(e))

    services: Dict[str, Service] = {}
    for svc in config.services:
        print(f"\n[서비스] {svc.id} ({svc.name})")

        print("  - GitHub 레포 동기화...", end=" ", flush=True)
        try:
            sync_repo(svc.github, svc.repo_path)
            print("OK")
        except RuntimeError as e:
            _fail(str(e))

        print("  - 데이터베이스 연결...", end=" ", flush=True)
        try:
            database = Database(svc.database)
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
    agent = ClaudeAgent(model=config.claude_model)
    server = WebServer(agent=agent, auth=auth, services=services)

    port = config.port
    print("CS 담당자는 웹 브라우저에서 아래 주소로 접속하세요:")
    print(f"  - 이 PC에서:     http://localhost:{port}")
    print(f"  - 같은 네트워크: http://<이 PC의 IP주소>:{port}")
    print(f"\n사용자 {len(config.users)}명 · 서비스 {len(config.services)}개 로드됨.")
    print("종료하려면 Ctrl+C 를 누르세요.\n")

    web.run_app(
        server.build_app(),
        host=config.host,
        port=port,
        print=lambda *args: None,
    )


if __name__ == "__main__":
    main()
