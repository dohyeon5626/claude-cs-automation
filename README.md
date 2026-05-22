# CS Automation — Claude 기반 CS 데이터 조회 시스템

CS(고객서비스) 담당자가 자연어로 질문하면, 개발자 PC에서 동작하는 Claude가
데이터베이스를 조회해 결과를 Markdown으로 정리해 주는 데스크탑 + 서버 시스템입니다.

```
CS 담당자 PC (cs-desktop)
        │  WebSocket
        ▼
개발자 PC (cs-server) ── Claude CLI ──▶ GitHub 레포 (코드/문서 파악)
        │
        ▼
     MySQL DB
```

- **cs-desktop** — CS 담당자가 사용하는 PyQt6 데스크탑 앱
- **cs-server** — 개발자 PC에서 실행하는 WebSocket 서버. 질문을 받아 Claude로 처리

여러 CS 담당자가 한 명의 개발자 PC(서버)에 접속해 사용하는 구조입니다.

---

## 동작 방식

1. CS 담당자가 데스크탑 앱에서 서버에 접속하고 서비스를 선택합니다.
2. 질문을 입력하면 서버로 전송됩니다.
3. 서버는 GitHub 레포를 최신으로 pull하고, DB 스키마를 분석합니다.
4. 개발자 PC의 **Claude CLI**가 레포 코드와 스키마를 파악해 SELECT 쿼리를 만들고,
   서버가 이를 실행합니다. (Claude는 필요 시 여러 번 조회합니다.)
5. Claude가 결과를 Markdown으로 정리해 데스크탑 앱에 표시합니다.

> 모든 쿼리는 **SELECT 전용**으로 검증됩니다. 데이터를 변경하는 쿼리는 실행되지 않습니다.

---

## 개발자(서버 운영자) PC 준비사항

서버는 개발자 PC에서 실행되며, 아래 항목이 모두 준비되어 있어야 시작됩니다.
하나라도 누락되면 서버가 시작되지 않고 오류를 표시합니다.

| 항목 | 설명 |
|------|------|
| Python 3.11+ | 서버 실행 |
| Git | 전역 설정 필요: `git config --global user.name`, `user.email` |
| Claude CLI | [Claude Code](https://docs.claude.com/claude-code) 설치 후 로그인. `claude` 명령이 PATH에 있어야 함 |
| MySQL 접근 | `config.yml`의 DB 계정으로 접속 가능해야 함 |
| GitHub 레포 접근 | `git clone/pull`이 비대화식으로 동작해야 함 (Private 레포는 SSH 키 또는 토큰 설정) |
| 네트워크 | CS 담당자 PC에서 접속할 수 있도록 WebSocket 포트(기본 8765)를 방화벽에서 개방 |

서버가 켜져 있는 동안에만 CS 담당자가 접속할 수 있으므로, 개발자 PC에서 서버를
계속 실행해 두어야 합니다.

---

## 서버 실행 (개발자 PC)

```bash
cd cs-server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`config.yml`을 열어 설정을 입력합니다:

```yaml
server:
  host: "0.0.0.0"
  port: 8765

database:
  host: "localhost"
  port: 3306
  name: "your_database"
  user: "your_user"
  password: "your_password"      # 환경변수 DB_PASSWORD로 대체 가능

github:
  repo_url: "https://github.com/yourorg/yourrepo"
  branch: "main"
  local_path: "./repo"           # 서버가 레포를 클론할 로컬 경로

claude:
  model: "sonnet"                # 비워두면 CLI 기본 모델 사용

services:                        # 데스크탑 앱에 표시할 서비스 목록
  - id: "order_inquiry"
    name: "주문 조회"
    description: "고객 주문 관련 정보를 조회합니다"
  # 필요한 서비스를 자유롭게 추가하세요
```

서버를 실행합니다:

```bash
python main.py
```

시작 시 Git 설정, GitHub 레포, MySQL 연결, 스키마, Claude CLI를 차례로 검증합니다.

---

## 데스크탑 앱 실행 (CS 담당자 PC)

```bash
cd cs-desktop
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

**최초 실행 시** 서버 IP와 사용자 ID를 입력하는 화면이 나옵니다.
입력 후 저장하면 바로 연결되며, 다음 실행부터는 자동으로 연결됩니다.

### 사용 순서

1. **초기 설정** — 서버 IP, 포트, 사용자 ID 입력 (개발자에게 서버 IP를 받으세요)
2. **서비스 선택** — 서버에서 받아온 서비스 목록에서 담당 서비스 선택
3. **질문** — 자연어로 질문 입력 (Enter: 전송 / Shift+Enter: 줄바꿈)

설정은 채팅 화면 상단의 "설정" 버튼에서 언제든 변경할 수 있으며,
"서비스 변경" 버튼으로 다른 서비스를 다시 선택할 수 있습니다.

설정값은 `~/.cs-desktop/settings.json`에 저장됩니다.

---

## 트러블슈팅

| 증상 | 확인 사항 |
|------|-----------|
| 서버: Git 설정 오류 | `git config --global user.name`, `user.email` 설정 |
| 서버: DB 연결 실패 | `config.yml`의 `database` 항목, MySQL 실행 여부 |
| 서버: GitHub 클론 실패 | 레포 URL/브랜치, Private 레포 인증(SSH 키/토큰) |
| 서버: Claude CLI 오류 | `claude` 설치 여부, 로그인 상태(`claude` 실행해 확인) |
| 데스크탑: 연결 실패 | 서버 실행 여부, 서버 IP/포트, 방화벽 포트 개방 |

---

## 직접 수정해서 사용하기

이 프로젝트는 자유롭게 가져다 수정해 사용할 수 있도록 만들어졌습니다.

- **서비스 목록** — `cs-server/config.yml`의 `services` 항목에서 추가/수정
- **Claude 동작 방식** — `cs-server/claude_handler.py`의 프롬프트 수정
- **데스크탑 UI** — `cs-desktop/ui/` 의 각 화면 파일 수정

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포하실 수 있습니다.
