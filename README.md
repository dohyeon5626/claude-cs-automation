# CS Automation

CS(고객서비스) 담당자가 **웹 브라우저에서 자연어로 질문**하면, Claude가
데이터베이스를 조회해 답변을 정리해 주는 시스템입니다.

예) "어제 주문 중 배송 안 된 건 몇 개야?" → Claude가 알아서 SQL을 만들어 조회 → 표로 정리해 답변

---

## 어떻게 동작하나요?

```
   CS 담당자                 서버 (개발자 PC)              데이터 출처
 ┌───────────┐   질문    ┌──────────────────┐         ┌──────────────┐
 │  웹 브라우저 │ ───────▶ │  Claude 가 SQL 작성  │ ──────▶ │  MySQL DB     │
 │           │ ◀─────── │  → 조회 → 답변 정리   │ ◀────── │  GitHub 레포   │
 └───────────┘   답변    └──────────────────┘         └──────────────┘
```

1. CS 담당자가 웹 페이지에 접속해 **아이디/비밀번호로 로그인**합니다.
2. 본인에게 허용된 **서비스**를 하나 고릅니다.
3. 질문을 입력하면 서버가 Claude에게 처리를 맡깁니다.
4. Claude는 해당 서비스의 **GitHub 레포(코드/문서)**와 **DB 스키마**를 살펴본 뒤
   SELECT 쿼리를 만들고, 서버가 그 쿼리를 실행해 결과를 Claude에게 다시 전달합니다.
5. Claude가 결과를 보기 좋게 정리해 웹 페이지에 보여 줍니다.

> **안전장치**: 데이터를 바꾸는 쿼리(INSERT/UPDATE/DELETE 등)는 실행되지 않습니다.
> 오직 조회(SELECT)만 가능합니다. Claude는 DB에 직접 연결하지 않고, 서버를 통해서만
> 조회할 수 있습니다.

---

## 서비스란?

이 시스템은 **여러 서비스**를 다룰 수 있습니다. 서비스 하나는 곧 "조회 대상 하나"입니다.

각 서비스는 자기만의 **GitHub 레포**와 (선택적으로) **데이터베이스**를 가집니다.
"주문 서비스"와 "회원 서비스"는 서로 다른 DB·레포를 바라보고,
"지식 베이스 서비스" 같은 건 DB 없이 레포 문서만으로 답변할 수도 있습니다.
사용자마다 어떤 서비스에 접근할 수 있는지도 따로 정합니다.

---

## 준비물 (서버를 켜는 PC)

서버는 개발자 PC에서 실행됩니다. 아래가 모두 준비되어야 서버가 켜집니다.
하나라도 빠지면 서버가 시작되지 않고 어디가 문제인지 알려 줍니다.

| 준비물 | 설명 |
|--------|------|
| Python 3.11+ | 서버 실행 |
| Git | `git config --global user.name` / `user.email` 설정 |
| Claude CLI | [Claude Code](https://docs.claude.com/claude-code) 설치 + 로그인 |
| MySQL 접근 | 각 서비스의 DB 계정으로 접속 가능 (DB가 있는 서비스에 한함) |
| GitHub 레포 접근 | 각 서비스 레포를 `git clone` 할 수 있어야 함 |

CS 담당자는 **아무것도 설치할 필요 없이** 브라우저만 있으면 됩니다.

---

## 설정하기 (config.yml)

`config.yml` 파일 하나로 모든 것을 설정합니다.

```yaml
server:
  port: 8765                # 웹 접속 포트

claude:
  model: "sonnet"
  # path: "/path/to/claude"   # PATH 에 'claude' 가 없으면 절대 경로 지정

# 서비스: 조회 대상마다 하나씩. database 는 선택 사항.
services:
  - id: "order"
    name: "주문 서비스"
    description: "주문 조회 및 배송 상태 확인"
    github:
      url: "https://github.com/yourorg/order-service"
      branch: "main"
    database:
      host: "localhost"
      port: 3306
      name: "order_db"
      user: "readonly_user"
      password: "db_password"

  - id: "knowledge"
    name: "지식 베이스"
    description: "사내 매뉴얼/문서 검색"
    github:
      url: "https://github.com/yourorg/knowledge-base"
      branch: "main"
    # database 없음 — Claude가 레포 문서만 보고 답합니다

# 사용자: 웹에 로그인하는 계정
users:
  - id: "admin"
    password: "changeme"
    name: "관리자"
    services: ["*"]           # ["*"] = 모든 서비스 접근 가능

  - id: "cs001"
    password: "changeme"
    name: "김상담"
    services: ["order"]       # 접근 가능한 서비스 id 목록
```

- **서비스 추가** — `services:` 아래에 항목을 더 적습니다.
- **데이터베이스 생략 가능** — `database:` 키를 빼면 DB 없이 레포만 사용합니다.
- **사용자 추가** — `users:` 아래에 항목을 더 적습니다.
- 비밀번호는 `config.yml` 에 그대로 저장되므로 파일 권한에 유의하세요.

---

## 실행하기

가상환경(venv) 안에서 실행하는 걸 권장합니다. 시스템 파이썬을 더럽히지 않습니다.

```bash
# 1) 가상환경 만들기 (최초 1회)
python -m venv .venv

# 2) 가상환경 활성화 (터미널 열 때마다)
source .venv/bin/activate          # macOS / Linux
# 또는 (Windows PowerShell)
.venv\Scripts\Activate.ps1

# 3) 의존성 설치 (최초 1회)
pip install -r requirements.txt

# 4) config.yml 작성 (위 설명 참고)

# 5) 서버 실행
python run.py
```

> 매번 활성화하기 귀찮으면 활성화 없이 직접 실행해도 됩니다:
> ```bash
> .venv/bin/python run.py        # macOS / Linux
> .venv\Scripts\python run.py    # Windows
> ```

서버가 켜지면 시작 검증(Git · Claude CLI · 서비스별 DB/레포)을 거친 뒤
**접속 주소를 화면에 출력합니다.**

```
CS 담당자는 아래 주소로 웹 브라우저에서 접속하세요:
  - 이 PC에서:           http://localhost:8765
  - 같은 WiFi의 다른 PC: http://192.168.0.15:8765
```

---

## CS 담당자가 접속하기 (같은 WiFi)

서버와 **같은 WiFi(같은 네트워크)** 에 연결된 PC라면 누구나 접속할 수 있습니다.

1. 서버 운영자가 서버를 실행한 뒤, **콘솔에 표시된 IP 주소** (예: `http://192.168.0.15:8765`)를 알려 줍니다.
2. CS 담당자는 그 주소를 브라우저에 입력합니다.
3. 로그인 → 서비스 선택 → 질문.

> **접속이 안 될 때**
> - 서버 PC와 **같은 WiFi**에 연결되어 있는지 확인하세요.
> - 서버 PC의 방화벽이 포트(`8765`)를 막고 있지는 않은지 확인하세요.

---

## 폴더 구조

```
claude-cs-automation/
├── run.py            ← 실행 진입점 (python run.py)
├── config.yml        ← 설정 파일
├── requirements.txt
└── src/              ← 애플리케이션 코드
    ├── main.py        시작 검증 + 서버 실행
    ├── config.py      config.yml 읽기
    ├── auth.py        로그인/인증
    ├── database.py    MySQL 조회 (서비스별)
    ├── repository.py  GitHub 레포 동기화 (서비스별)
    ├── service.py     서비스 런타임
    ├── agent.py       Claude 호출 및 질의 처리
    ├── server.py      웹 서버 (페이지 · API · WebSocket)
    └── web/           웹 페이지 (HTML · CSS · JS)
```

`repos/` 폴더는 첫 실행 시 자동으로 만들어지며, 각 서비스의 GitHub 레포가
`repos/<서비스 id>/` 에 clone 됩니다.

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
  -d '{"service_id":"order","message":"오늘 들어온 주문 수는?"}'
```

---

## 문제 해결

| 증상 | 확인할 것 |
|------|-----------|
| Git 설정 오류 | `git config --global user.name`, `user.email` |
| DB 연결 실패 | 해당 서비스의 `database` 설정, MySQL 실행 여부 |
| GitHub 클론 실패 | 레포 url/branch, Private 레포 인증(SSH 키/토큰) |
| Claude CLI 오류 | `claude` 설치 및 로그인 상태 |
| 웹 접속 안 됨 | 같은 WiFi 여부, 콘솔에 표시된 IP/포트, 방화벽 |
| 로그인 실패 | `config.yml` 의 `users` 항목 |

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포할 수 있습니다.
