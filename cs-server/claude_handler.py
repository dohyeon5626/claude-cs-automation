import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import anthropic


@dataclass
class UserSession:
    user_id: str
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    service_description: Optional[str] = None
    history: List[Dict[str, str]] = field(default_factory=list)

    def set_service(self, service_id: str, name: str, description: str):
        self.service_id = service_id
        self.service_name = name
        self.service_description = description
        self.history = []


class ClaudeHandler:
    def __init__(self, api_key: str, model: str, schema_context: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._schema_context = schema_context

    def _build_system_prompt(self, service_name: str, service_description: str) -> str:
        return (
            f"당신은 CS(고객서비스) 팀의 데이터베이스 조회 전문 어시스턴트입니다.\n\n"
            f"## 현재 담당 서비스\n"
            f"- 이름: {service_name}\n"
            f"- 설명: {service_description}\n\n"
            f"## 데이터베이스 스키마\n"
            f"{self._schema_context}\n\n"
            f"## 규칙\n"
            f"1. SELECT 쿼리만 생성하세요. INSERT, UPDATE, DELETE, DROP, TRUNCATE는 절대 금지입니다.\n"
            f"2. 비밀번호, 카드번호, 주민등록번호 등 민감한 컬럼은 조회하지 마세요.\n"
            f"3. 전체 테이블 덤프처럼 과도하게 큰 요청은 거절하세요.\n"
            f"4. 쿼리는 반드시 ```sql ... ``` 코드 블록 안에만 작성하세요.\n"
            f"5. 처리 불가 요청이면 이유를 한국어로 명확히 설명하세요."
        )

    def generate_sql(
        self,
        session: UserSession,
        user_query: str,
    ) -> Tuple[bool, str]:
        """
        Ask Claude to validate the request and generate a SELECT query.
        Returns (is_valid, sql_query_or_rejection_reason).
        """
        system = self._build_system_prompt(
            session.service_name, session.service_description
        )

        session.history.append(
            {
                "role": "user",
                "content": (
                    f"CS 요청: {user_query}\n\n"
                    "이 요청을 처리할 MySQL SELECT 쿼리를 작성해주세요. "
                    "처리할 수 없는 요청이면 이유를 설명해주세요."
                ),
            }
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=session.history,
        )

        reply = response.content[0].text

        session.history.append({"role": "assistant", "content": reply})

        sql_match = re.search(r"```sql\s*(.*?)\s*```", reply, re.DOTALL | re.IGNORECASE)
        if sql_match:
            return True, sql_match.group(1).strip()

        return False, reply

    def format_results(
        self,
        original_query: str,
        sql: str,
        rows: List[Dict[str, Any]],
    ) -> str:
        """
        Format SQL results into readable Markdown for the CS agent.
        Runs as a standalone call (not part of session history).
        """
        if not rows:
            result_text = "조회 결과가 없습니다."
        else:
            headers = list(rows[0].keys())
            row_lines = []
            for row in rows[:50]:
                row_lines.append(
                    " | ".join(str(row.get(h, "")) for h in headers)
                )
            result_text = (
                f"컬럼: {', '.join(headers)}\n"
                + "\n".join(row_lines)
            )
            if len(rows) > 50:
                result_text += f"\n... 외 {len(rows) - 50}건 (총 {len(rows)}건)"

        prompt = (
            f"다음 데이터베이스 조회 결과를 CS 담당자가 보기 쉽게 Markdown 형식으로 정리해주세요.\n\n"
            f"**원래 CS 요청:** {original_query}\n\n"
            f"**실행된 SQL:**\n```sql\n{sql}\n```\n\n"
            f"**조회 결과:**\n{result_text}\n\n"
            f"표 형식, 요약 문장 등을 활용해 CS 담당자가 즉시 고객에게 안내할 수 있도록 정리해주세요."
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text
