import asyncio
import logging
import sys

from claude_handler import ClaudeHandler
from config import load_config
from db_handler import DatabaseHandler
from git_handler import check_git_config, get_schema_context, sync_repo
from ws_server import CSWebSocketServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def startup_checks(config) -> str:
    """
    Run all startup validations in order.
    Returns the schema context string on success.
    Exits the process on any failure.
    """

    print("=" * 60)
    print("  CS Automation Server - 시작 검증")
    print("=" * 60)

    # 1. Git config
    print("\n[1/3] Git 설정 확인...", end=" ", flush=True)
    try:
        check_git_config()
        print("OK")
    except RuntimeError as e:
        print("FAIL")
        print(f"\n오류: {e}")
        sys.exit(1)

    # 2. GitHub repo sync
    print("[2/3] GitHub 레포 동기화...", end=" ", flush=True)
    try:
        sync_repo(
            config.github_repo_url,
            config.github_branch,
            config.github_local_path,
        )
        schema_context = get_schema_context(config.github_local_path)
        print("OK")
    except RuntimeError as e:
        print("FAIL")
        print(f"\n오류: {e}")
        sys.exit(1)

    # 3. Database connection
    print("[3/3] 데이터베이스 연결 확인...", end=" ", flush=True)
    try:
        DatabaseHandler(
            host=config.db_host,
            port=config.db_port,
            database=config.db_name,
            user=config.db_user,
            password=config.db_password,
        )
        print("OK")
    except RuntimeError as e:
        print("FAIL")
        print(f"\n오류: {e}")
        sys.exit(1)

    print("\n모든 검증 통과. 서버를 시작합니다.\n")
    return schema_context


def main():
    try:
        config = load_config("config.yml")
    except (FileNotFoundError, ValueError) as e:
        print(f"설정 오류: {e}")
        sys.exit(1)

    schema_context = startup_checks(config)

    db = DatabaseHandler(
        host=config.db_host,
        port=config.db_port,
        database=config.db_name,
        user=config.db_user,
        password=config.db_password,
    )

    claude = ClaudeHandler(
        api_key=config.claude_api_key,
        model=config.claude_model,
        schema_context=schema_context,
    )

    server = CSWebSocketServer(config=config, db=db, claude=claude)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")


if __name__ == "__main__":
    main()
