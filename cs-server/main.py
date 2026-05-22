import logging
import sys

from aiohttp import web

from auth import Authenticator
from claude_handler import ClaudeHandler, check_claude_cli
from config import load_config
from db_handler import DatabaseHandler
from git_handler import check_git_config, sync_repo
from web_server import WebServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _fail(message: str):
    print("FAIL")
    print(f"\n오류: {message}")
    sys.exit(1)


def startup_checks(config) -> DatabaseHandler:
    """
    Run all startup validations in order.
    Returns the DatabaseHandler on success. Exits the process on any failure.
    """

    print("=" * 60)
    print("  CS Automation Server - 시작 검증")
    print("=" * 60)

    # 1. Git config
    print("\n[1/5] Git 설정 확인...", end=" ", flush=True)
    try:
        check_git_config()
        print("OK")
    except RuntimeError as e:
        _fail(str(e))

    # 2. GitHub repo sync (clone or pull)
    print("[2/5] GitHub 레포 동기화...", end=" ", flush=True)
    try:
        sync_repo(
            config.github_repo_url,
            config.github_branch,
            config.github_local_path,
        )
        print("OK")
    except RuntimeError as e:
        _fail(str(e))

    # 3. Database connection
    print("[3/5] 데이터베이스 연결 확인...", end=" ", flush=True)
    db = None
    try:
        db = DatabaseHandler(
            host=config.db_host,
            port=config.db_port,
            database=config.db_name,
            user=config.db_user,
            password=config.db_password,
        )
        print("OK")
    except RuntimeError as e:
        _fail(str(e))

    # 4. Live schema introspection
    print("[4/5] 데이터베이스 스키마 분석...", end=" ", flush=True)
    try:
        db.get_schema_introspection()
        print("OK")
    except RuntimeError as e:
        _fail(str(e))

    # 5. Claude CLI availability & authentication
    print("[5/5] Claude CLI 확인...", end=" ", flush=True)
    try:
        check_claude_cli(config.claude_model)
        print("OK")
    except RuntimeError as e:
        _fail(str(e))

    print("\n모든 검증 통과. 서버를 시작합니다.\n")
    return db


def main():
    try:
        config = load_config("config.yml")
    except (FileNotFoundError, ValueError) as e:
        print(f"설정 오류: {e}")
        sys.exit(1)

    db = startup_checks(config)

    auth = Authenticator(config.users, config.services)
    claude = ClaudeHandler(
        model=config.claude_model,
        db_handler=db,
        github_branch=config.github_branch,
        repo_local_path=config.github_local_path,
    )
    server = WebServer(config=config, claude=claude, auth=auth)

    port = config.server_port
    print("CS 담당자는 웹 브라우저에서 아래 주소로 접속하세요:")
    print(f"  - 이 PC에서:     http://localhost:{port}")
    print(f"  - 같은 네트워크: http://<이 PC의 IP주소>:{port}")
    print(f"\n사용자 {len(config.users)}명 · 서비스 {len(config.services)}개 로드됨.")
    print("종료하려면 Ctrl+C 를 누르세요.\n")

    web.run_app(
        server.build_app(),
        host=config.server_host,
        port=port,
        print=lambda *args: None,
    )


if __name__ == "__main__":
    main()
