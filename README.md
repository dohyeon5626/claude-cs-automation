# CS Automation — Claude 기반 CS 데이터 조회 시스템

CS(고객서비스) 담당자가 웹 브라우저에서 자연어로 질문하면, 개발자 PC에서 동작하는
Claude가 데이터베이스를 조회해 결과를 정리해 주는 시스템입니다.

```
CS 담당자 (웹 브라우저)
        │  http / websocket
        ▼
개발자 PC (cs-server) ── Claude CLI ──▶ GitHub 레포 (코드/문서 파악)
        │
        ▼
     MySQL DB
```

CS 담당자는 **별도 설치 없이** 웹 페이지 주소로 접속해 로그인만 하면 사용할 수 있습니다.
서버는 웹 페이지 · REST API · WebSocket을 모두 제공합니다.

---

## 동작 방식

1. CS 담당자가 웹 페이지에 접속해 **아이디/비밀번호로 로그인**합니다.
2. 본인에게 허용된 **서비스 목록**이 표시되며, 하나를 선택합니다.
3. 질문을 입력하면 서버로 전송됩니다.
4. 서버는 GitHub 레포를 최신으로 pull하고, DB 스키마를 분석합니다.
5. 개발자 PC의 **Claude CLI**가 레포 코드와 스키마를 파악해 SELECT 쿼리를 만들고,
   서버가 이를 실행합니다. (Claude는 필요 시 여러 번 조회합니다.)
6. Claude가 결과를 정리해 웹 페이지에 표시합니다.

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
| 네트워크 | CS 담당자가 접속할 수 있도록 웹 포트(기본 8765)를 방화벽에서 개방 |

서버가 켜져 있는 동안에만 CS 담당자가 접속할 수 있으므로, 개발자 PC에서 서버를
계속 실행해 두어야 합니다.

---

## 서버 설정

`config.yml`을 열어 설정을 입력합니다.

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
  local_path: "./repo"

claude:
  model: "sonnet"                # 비워두면 CLI 기본 모델 사용

services:                        # CS 담당자가 선택할 수 있는 서비스
  - id: "order_inquiry"
    name: "주문 조회"
    description: "고객 주문 관련 정보를 조회합니다"

users:                           # 웹에 로그인할 수 있는 사용자
  - id: "admin"
    password: "changeme"
    name: "관리자"
    services: ["*"]              # ["*"] = 모든 서비스 접근 가능
  - id: "cs001"
    password: "changeme"
    name: "김상담"
    services: ["order_inquiry"]  # 접근 가능한 서비스 id 목록
```

- **services** — CS 담당자가 선택할 수 있는 서비스 목록
- **users** — 로그인 계정. 사용자마다 접근 가능한 서비스를 지정합니다
  - `services: ["*"]` 이면 모든 서비스 접근 가능
  - 비밀번호는 `config.yml`에 평문으로 저장되므로 파일 접근 권한에 유의하세요

---

## 서버 실행 (개발자 PC)

```bash
cd cs-server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

시작 시 Git 설정, GitHub 레포, MySQL 연결, 스키마, Claude CLI를 차례로 검증한 뒤
웹 서버가 실행됩니다.

---

## CS 담당자 사용법

웹 브라우저에서 서버 주소로 접속합니다 (개발자에게 주소를 받으세요).

```
http://<서버 PC의 IP주소>:8765
```

1. **로그인** — 발급받은 아이디와 비밀번호 입력
2. **서비스 선택** — 본인에게 허용된 서비스 중 하나 선택
3. **질문** — 자연어로 질문 입력 (Enter 전송 · Shift+Enter 줄바꿈)

상단의 "서비스 변경" 버튼으로 다른 서비스를 다시 선택할 수 있습니다.

---

## REST API

웹 페이지 외에 프로그램에서 직접 호출할 수도 있습니다.

```bash
# 1) 로그인 → 토큰 발급
curl -X POST http://SERVER:8765/api/login \
  -H "Content-Type: application/json" \
  -d '{"user_id":"cs001","password":"changeme"}'

# 2) 질문 (발급받은 토큰 사용)
curl -X POST http://SERVER:8765/api/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <발급받은_토큰>" \
  -d '{"service_id":"order_inquiry","message":"오늘 들어온 주문 수는?"}'
```

실시간 진행 상태가 필요하면 `/ws` WebSocket을 사용합니다 (웹 페이지가 사용하는 방식).

---

## 트러블슈팅

| 증상 | 확인 사항 |
|------|-----------|
| 서버: Git 설정 오류 | `git config --global user.name`, `user.email` 설정 |
| 서버: DB 연결 실패 | `config.yml`의 `database` 항목, MySQL 실행 여부 |
| 서버: GitHub 클론 실패 | 레포 URL/브랜치, Private 레포 인증(SSH 키/토큰) |
| 서버: Claude CLI 오류 | `claude` 설치 여부, 로그인 상태(`claude` 실행해 확인) |
| 웹: 접속 안 됨 | 서버 실행 여부, 서버 IP/포트, 방화벽 포트 개방 |
| 웹: 로그인 실패 | `config.yml`의 `users` 항목, 아이디/비밀번호 |

---

## 직접 수정해서 사용하기

이 프로젝트는 자유롭게 가져다 수정해 사용할 수 있도록 만들어졌습니다.

- **서비스 / 사용자** — `cs-server/config.yml`에서 추가·수정
- **Claude 동작 방식** — `cs-server/claude_handler.py`의 프롬프트 수정
- **웹 화면 디자인** — `cs-server/web/`의 `index.html` · `style.css` · `app.js` 수정

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포하실 수 있습니다.
