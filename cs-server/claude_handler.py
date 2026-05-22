import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from db_handler import DatabaseHandler
from git_handler import pull_repo

logger = logging.getLogger(__name__)

# Safety cap so a runaway conversation can't loop forever
_MAX_ITERATIONS = 12

# Per-call timeout for the Claude CLI (seconds)
_CLI_TIMEOUT = 240

# Truncate oversized query results before sending back to Claude
_MAX_RESULT_CHARS = 20000

_SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def check_claude_cli(model: str):
    """
    Verify the Claude CLI is installed and authenticated.
    Raises RuntimeError on any failure (server must not start).
    """
    try:
        version = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Claude CLI('claude' 명령)를 찾을 수 없습니다.\n"
            "  Claude Code를 설치하고 PATH에 등록하세요: https://docs.claude.com/claude-code"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI 버전 확인 중 시간이 초과되었습니다.")

    if version.returncode != 0:
        raise RuntimeError(f"Claude CLI 실행 실패: {version.stderr.strip()}")

    # Authentication / runnability check via a minimal print-mode call
    cmd = ["claude", "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    try:
        ping = subprocess.run(
            cmd,
            input="OK",
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI 인증 확인 중 시간이 초과되었습니다.")

    if ping.returncode != 0:
        raise RuntimeError(
            "Claude CLI 실행/인증에 실패했습니다. 'claude' 로그인 상태를 확인하세요.\n"
            f"  {ping.stderr.strip()}"
        )
    try:
        data = json.loads(ping.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("Claude CLI 응답을 해석할 수 없습니다.")
    if data.get("is_error"):
        raise RuntimeError(f"Claude CLI 오류: {data.get('result', '')}")


@dataclass
class UserSession:
    user_id: str
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    service_description: Optional[str] = None
    # Claude CLI session id — gives each user a persistent conversation context
    cli_session_id: Optional[str] = None

    def set_service(self, service_id: str, name: str, description: str):
        self.service_id = service_id
        self.service_name = name
        self.service_description = description
        self.cli_session_id = None  # fresh conversation when service changes


class ClaudeHandler:
    def __init__(
        self,
        model: str,
        db_handler: DatabaseHandler,
        github_branch: str,
        repo_local_path: str,
    ):
        self._model = model
        self._db = db_handler
        self._branch = github_branch
        self._repo_path = repo_local_path

    def process_query(
        self,
        session: UserSession,
        user_query: str,
        status_callback: Callable[[str], None],
    ) -> str:
        """
        Pull the repo, refresh the schema, then run an agentic loop where Claude
        explores the repo and issues SELECT queries until it produces an answer.
        Blocking — run inside an executor.
        """
        # 1. Pull the GitHub repo (non-fatal: fall back to the existing checkout)
        status_callback("레포지토리를 동기화하고 있습니다...")
        try:
            pull_repo(self._branch, self._repo_path)
        except RuntimeError as e:
            logger.warning(f"Repo pull failed, using existing checkout: {e}")

        # 2. Refresh the live database schema
        status_callback("데이터베이스 스키마를 확인하고 있습니다...")
        live_schema = self._db.get_schema_introspection()

        # 3. Agentic loop
        turn_prompt = self._build_initial_prompt(session, live_schema, user_query)

        for iteration in range(_MAX_ITERATIONS):
            status_callback(
                "Claude가 분석 중입니다..."
                if iteration == 0
                else "Claude가 추가 분석 중입니다..."
            )

            reply, new_session_id = self._invoke_cli(
                turn_prompt, session.cli_session_id
            )
            if session.cli_session_id is None:
                session.cli_session_id = new_session_id

            action, payload = self._parse_action(reply)

            if action == "QUERY":
                preview = " ".join(payload.split())[:70]
                status_callback(f"DB 조회 중: {preview}...")
                turn_prompt = self._run_query(payload)
            else:  # ANSWER (or fallback)
                return payload

        return (
            "조회 단계가 너무 많아 처리를 중단했습니다. "
            "질문을 더 구체적으로 작성해 주세요."
        )

    # ── Prompt building ───────────────────────────────────────────────────────

    def _build_initial_prompt(
        self, session: UserSession, live_schema: str, user_query: str
    ) -> str:
        return (
            "# CS 데이터 조회 요청\n\n"
            "당신은 CS(고객서비스) 팀을 지원하는 데이터 조회 어시스턴트입니다.\n"
            "현재 작업 디렉터리는 대상 서비스의 GitHub 레포지토리입니다. "
            "도움이 된다면 레포의 파일을 직접 읽어 도메인과 데이터 구조를 파악하세요.\n\n"
            f"## 담당 서비스\n"
            f"- 이름: {session.service_name}\n"
            f"- 설명: {session.service_description}\n\n"
            f"## 데이터베이스 실시간 스키마\n"
            f"{live_schema}\n\n"
            "## 행동 규약 (매우 중요)\n"
            "데이터베이스 데이터가 필요하면, 응답을 다음 형식으로 작성하세요.\n"
            "  - 첫 줄: QUERY\n"
            "  - 그 다음 줄부터: ```sql 코드 블록``` 안에 SELECT 쿼리\n"
            "조회 결과는 다음 메시지로 전달됩니다. 필요하면 QUERY를 여러 번 반복할 수 있습니다.\n\n"
            "충분한 정보를 얻었으면, CS 담당자가 고객에게 바로 안내할 수 있는 최종 답변을 작성하세요.\n"
            "  - 첫 줄: ANSWER\n"
            "  - 그 다음 줄부터: 한국어 Markdown 답변 (표, 요약 문장 등 활용)\n\n"
            "## 규칙\n"
            "- SELECT 쿼리만 사용하세요. INSERT/UPDATE/DELETE/DROP/TRUNCATE는 절대 금지입니다.\n"
            "- 비밀번호, 카드번호, 주민등록번호 등 민감한 정보는 조회하거나 노출하지 마세요.\n"
            "- 전체 테이블 덤프처럼 과도하게 큰 요청은 거절하고 ANSWER로 사유를 설명하세요.\n"
            "- 처리할 수 없는 요청이면 ANSWER로 사유를 한국어로 설명하세요.\n\n"
            f"## CS 담당자 질문\n{user_query}"
        )

    def _query_result_prompt(self, sql: str, result_json: str) -> str:
        return (
            "## 직전 SQL 조회 결과\n"
            f"실행된 쿼리:\n```sql\n{sql}\n```\n\n"
            f"결과 (JSON):\n{result_json}\n\n"
            "위 결과를 바탕으로 다음 행동을 결정하세요. "
            "추가 조회가 필요하면 첫 줄 QUERY, 충분하면 첫 줄 ANSWER로 응답하세요."
        )

    def _query_error_prompt(self, sql: str, error: str) -> str:
        return (
            "## 직전 SQL 조회 오류\n"
            f"실행하려던 쿼리:\n```sql\n{sql}\n```\n\n"
            f"오류: {error}\n\n"
            "쿼리를 수정해 QUERY로 다시 시도하거나, "
            "불가능하면 ANSWER로 사유를 설명하세요."
        )

    # ── Claude CLI invocation ─────────────────────────────────────────────────

    def _invoke_cli(
        self, prompt: str, session_id: Optional[str]
    ) -> Tuple[str, Optional[str]]:
        """Call the Claude CLI in print mode. Returns (reply_text, session_id)."""
        cmd = ["claude", "-p", "--output-format", "json"]
        if self._model:
            cmd += ["--model", self._model]
        if session_id:
            cmd += ["--resume", session_id]

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                cwd=self._repo_path,
                timeout=_CLI_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude CLI 응답 시간이 초과되었습니다.")

        if proc.returncode != 0:
            raise RuntimeError(f"Claude CLI 실행 오류: {proc.stderr.strip()}")

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError("Claude CLI 응답을 해석할 수 없습니다.")

        if data.get("is_error"):
            raise RuntimeError(f"Claude 처리 오류: {data.get('result', '')}")

        return data.get("result", ""), data.get("session_id")

    # ── Response parsing & query execution ────────────────────────────────────

    @staticmethod
    def _parse_action(reply: str) -> Tuple[str, str]:
        """
        Parse Claude's reply. Returns (action, payload):
          - ("QUERY", sql_text)
          - ("ANSWER", markdown_text)
        Falls back to treating the whole reply as an answer.
        """
        stripped = reply.strip()
        first_line, _, rest = stripped.partition("\n")
        directive = first_line.strip().upper()

        if directive.startswith("QUERY"):
            sql_match = _SQL_BLOCK_RE.search(rest)
            sql = sql_match.group(1).strip() if sql_match else rest.strip()
            return "QUERY", sql

        if directive.startswith("ANSWER"):
            return "ANSWER", rest.strip() or stripped

        return "ANSWER", stripped

    def _run_query(self, sql: str) -> str:
        """Execute a SELECT query and build the next turn prompt."""
        if not sql:
            return self._query_error_prompt(sql, "SQL 쿼리가 비어 있습니다.")
        try:
            rows = self._db.execute_select(sql)
            result_json = json.dumps(rows, ensure_ascii=False, default=str)
            if len(result_json) > _MAX_RESULT_CHARS:
                result_json = (
                    result_json[:_MAX_RESULT_CHARS]
                    + "\n...(결과가 너무 커서 일부만 표시됨. 더 구체적인 조건으로 조회하세요.)"
                )
            return self._query_result_prompt(sql, result_json)
        except (ValueError, RuntimeError) as e:
            return self._query_error_prompt(sql, str(e))
