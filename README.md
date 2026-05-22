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
3. 질문을 입력하면, 서버가 Claude에게 처리를 맡깁니다.
4. Claude는 해당 서비스의 **GitHub 레포(코드/문서)**와 **DB 스키마**를 살펴본 뒤
   SELECT 쿼리를 만들고, 서버가 이를 실행합니다.
5. 결과를 보기 좋게 정리해 웹 페이지에 보여 줍니다.

> **안전장치**: 데이터를 바꾸는 쿼리(INSERT/UPDATE/DELETE 등)는 실행되지 않습니다.
> 오직 조회(SELECT)만 가능합니다.

---

## 서비스란?

이 시스템은 **여러 서비스**를 다룰 수 있습니다. 서비스 하나는 곧 "조회 대상 하나"입니다.

각 서비스는 **자기만의 데이터베이스와 GitHub 레포**를 가집니다. 예를 들어
"주문 서비스"와 "회원 서비스"는 서로 다른 DB·레포를 바라봅니다.
사용자마다 어떤 서비스에 접근할 수 있는지도 따로 정할 수 있습니다.

---

## 준비물 (서버를 켜는 PC)

서버는 개발자 PC에서 실행됩니다. 아래가 모두 준비되어야 서버가 켜집니다.
하나라도 빠지면 서버가 시작되지 않고 어디가 문제인지 알려 줍니다.

| 준비물 | 설명 |
|--------|------|
| Python 3.11+ | 서버 실행 |
| Git | `git config --global user.name` / `user.email` 설정 |
| Claude CLI | [Claude Code](https://docs.claude.com/claude-code) 설치 + 로그인 |
| MySQL 접근 | 각 서비스의 DB 계정으로 접속 가능해야 함 |
| GitHub 레포 접근 | 각 서비스 레포를 `git clone` 할 수 있어야 함 |

CS 담당자는 **아무것도 설치할 필요 없이** 브라우저만 있으면 됩니다.

---

## 설정하기 (config.yml)

`config.yml` 파일 하나로 모든 것을 설정합니다.

```yaml
server:
  host: "0.0.0.0"          # 다른 PC에서 접속하려면 0.0.0.0
  port: 8765

claude:
  model: "sonnet"

# 서비스: 조회 대상마다 하나씩. DB와 GitHub를 각각 설정합니다.
services:
  - id: "order"
    name: "주문 서비스"
    description: "주문 조회 및 배송 상태 확인"
    database:
      host: "localhost"
      port: 3306
      name: "order_db"
      user: "readonly_user"
      password: "db_password"
    github:
      url: "https://github.com/yourorg/order-service"
      branch: "main"

# 사용자: 웹에 로그인하는 계정
users:
  - id: "admin"
    password: "changeme"
    name: "관리자"
    services: ["*"]          # ["*"] = 모든 서비스 접근 가능

  - id: "cs001"
    password: "changeme"
    name: "김상담"
    services: ["order"]      # 접근 가능한 서비스 id 목록
```

- **서비스를 추가**하려면 `services:` 아래에 항목을 더 적으면 됩니다.
- **사용자를 추가**하려면 `users:` 아래에 항목을 더 적습니다.
- 비밀번호는 `config.yml`에 그대로 저장되므로 파일 접근 권한에 유의하세요.

---

## 실행하기

```bash
# 1) 의존성 설치
pip install -r requirements.txt

# 2) config.yml 작성 (위 설명 참고)

# 3) 서버 실행
python run.py
```

서버가 켜지면 시작 검증(Git · Claude CLI · 서비스별 DB/레포)을 차례로 거친 뒤
접속 주소를 보여 줍니다.

---

## CS 담당자 사용법

웹 브라우저에서 서버 주소로 접속합니다 (주소는 서버 운영자에게 받으세요).

```
http://<서버 PC의 IP주소>:8765
```

1. **로그인** — 발급받은 아이디/비밀번호 입력
2. **서비스 선택** — 본인에게 허용된 서비스 중 하나 선택
3. **질문** — 자연어로 입력 (Enter 전송 · Shift+Enter 줄바꿈)

상단의 "서비스 변경" 버튼으로 다른 서비스를 다시 고를 수 있습니다.

---

## 폴더 구조

```
claude-cs-automation/
├── run.py            ← 실행 진입점 (python run.py)
├── config.yml        ← 설정 파일
├── requirements.txt
└── csagent/          ← 애플리케이션 코드
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
| 웹 접속 안 됨 | 서버 실행 여부, IP/포트, 방화벽 |
| 로그인 실패 | `config.yml`의 `users` 항목 |

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포할 수 있습니다.
