# Claude CS Automation

![License](https://img.shields.io/github/license/dohyeon5626/claude-cs-automation?style=flat&color=green) ![GitHub Tag](https://img.shields.io/github/v/tag/dohyeon5626/claude-cs-automation?style=flat&color=green) ![Powered by Claude](https://img.shields.io/badge/Powered_by-Claude-cc785c?style=flat)
<br/>

<img width="100%" align=center alt="readme" src="https://github.com/user-attachments/assets/426feddd-1b17-4142-ac16-95b373801792">
<br/><br/>

CS 담당자가 질문하면 Claude가 GitHub 코드와 데이터베이스를 조회해 답해 주는 프로젝트입니다.<br/>
```
예) "어제 주문 중 배송 안 된 건 몇 개야?" → SQL 자동 생성 → DB 조회 → 표로 정리해 답변<br/>
예) "이 기능 어떻게 설정돼 있지?" → 레포 코드 탐색 → 답변<br/>
```
개발자가 사소한 질문에 답하느라 드는 시간을 줄이려고 만들었습니다.
기본 구조는 **한 프로젝트당 하나의 DB**를 가정하며,
현재 **MySQL · PostgreSQL · Oracle** 을 지원합니다.
레포를 받아 `config.yml`만 채우면 바로 시작할 수 있고, 회사에서 일할 때 자기 PC에 켜 두기만 하면 됩니다.<br/>


---

### 동작 방식
질문이 들어오면 Claude가 SQL을 만들고, 서버가 안전 검증 후 실행해 결과를 정리합니다.<br/>
데이터를 바꾸는 쿼리(INSERT/UPDATE/DELETE)는 **절대 실행되지 않습니다.**
```
- CS 담당자 (웹 브라우저)
- ↓ 질문
- 서버 (개발자 PC) ─ Claude CLI ─ GitHub 레포 (코드 파악)
- ↓
- DB (SELECT만)  ── MySQL · PostgreSQL · Oracle
- ↓ 결과
- Markdown 답변 → 웹 브라우저
```

### 준비물 (서버 운영자 PC)
서버는 개발자 PC에서 실행합니다. 아래가 준비되어 있지 않으면 서버가 시작되지 않고, 어디가 문제인지 알려 줍니다.<br/>
CS 담당자는 브라우저만 있으면 됩니다.
```
- Python 3.11+

- Git              git config --global user.name / user.email 설정
- GitHub 레포 접근  git clone/pull이 비대화식으로 동작 (Private은 SSH 키/토큰)

- Claude CLI       Claude Code 설치. 'claude'가 PATH에 있어야 함 (로그아웃 상태여도
                   서버는 시작되고, 관리자가 웹 UI에서 로그인 가능)

- DB 접근          (DB가 있는 서비스에 한함) 서비스별 계정으로 접속 가능
                   MySQL · PostgreSQL · Oracle — 엔진별 드라이버는 자동 설치
```
DB 계정은 **read-only 권한**으로 만들어 두는 걸 권장합니다. SELECT 외 쿼리는 서버에서 이미 차단되지만, DB 계정 자체가 읽기 전용이면 마지막 방어선이 됩니다.

### 실행 (4단계)

#### 1. 서비스 정의
"서비스 하나 = 조회 대상 하나"입니다. 서비스마다 GitHub 레포(필수)와 DB(선택)를 갖습니다. 레포만 있으면 코드·문서 탐색, DB까지 있으면 SQL 자동 생성·조회까지 가능합니다. 서비스는 여러 개 동시에 운영할 수 있어요.

#### 2. `config.yml` 작성
필요한 건 4개 섹션. 아래 예시를 그대로 받아 빈칸만 본인 환경에 맞춰 채우면 됩니다.

```yaml
server:
  port: 8765                            # 웹 접속 포트

claude:
  model: "sonnet"                       # 사용할 Claude 모델

services:                               # 조회 대상 — 여러 개 등록 가능
  - id: "order"                         # 내부 식별자 (영문/숫자/_)
    name: "주문 서비스"                 # 사이드바·헤더에 표시될 이름
    github:                             # 필수 — Claude가 코드를 읽음
      url: "https://github.com/yourorg/order-service"
      branch: "main"
    database:                           # 선택 — 없는 서비스면 이 블록 통째로 삭제
      kind: "mysql"                     # mysql | postgres | oracle (생략 시 mysql)
      host: "localhost"
      port: 3306
      name: "order_db"
      user: "readonly_user"
      password: "db_password"

users:                                  # 웹에 로그인할 계정 — 여러 명 등록 가능
  - id: "admin"
    password: "changeme"
    services: ["*"]                     # 접근 허용 서비스 id — ["*"]는 전체
    admin: true                         # 통계·Claude CLI 관리 권한 (선택)
```

채워야 할 곳: `services[].github.url` / `database` 정보 / `users[]` 의 실제 계정. `brand`(앱 이름·로고)·서비스별 `logo`·`description` 등 부가 옵션은 `config.yml` 안의 주석에 정리되어 있습니다.

#### 3. 서버 시작
```
python run.py
```
첫 실행에서 알아서 `.venv` 를 만들고, 공통 의존성과 `config.yml` 의 `kind` 값에 맞는 DB 드라이버(`requirements-<kind>.txt`)를 설치한 뒤 서버를 시작합니다. 두 번째부터는 의존성 체크만 빠르게 거치고 바로 기동 (이미 venv 안이면 그 venv를 그대로 사용). 시작 검증(Git · Claude CLI · 레포 · DB)을 통과하면 콘솔에 접속 주소가 출력됩니다. 종료는 Ctrl+C.

<details>
<summary>수동으로 환경을 관리하고 싶다면</summary>

```
- python -m venv .venv && source .venv/bin/activate    # macOS/Linux
  (Windows PowerShell: .venv\Scripts\Activate.ps1)
- pip install -r requirements.txt                      # 공통
- pip install -r requirements-mysql.txt                # 본인 DB만 선별 (또는 -postgres / -oracle)
- python run.py
```
</details>

#### 4. CS 담당자에게 주소 공유
콘솔에 `http://192.168.x.x:8765` 형태로 LAN IP가 자동 표시됩니다. 같은 WiFi에 있는 동료에게 그 주소를 알려주면 끝.

CS 담당자 사용법:
```
- 주소창에 http://<서버 PC IP>:8765 입력
- 로그인 (한 번 하면 새로고침해도 유지됨)
- 사이드바에서 서비스 선택 (마지막 사용 서비스 자동 선택됨)
- Enter 전송 · Shift+Enter 줄바꿈
```

IP를 수동으로 확인하고 싶다면:
```
- macOS    터미널에서  ipconfig getifaddr en0
- Windows  cmd 에서   ipconfig  → "IPv4 주소" 항목
- Linux    터미널에서  hostname -I
```

접속 안 될 때 → 같은 WiFi인지, 방화벽이 포트(8765) 막고 있지 않은지 확인.

---

### 기타 기능

#### 관리자 기능
`config.yml` 의 사용자에 `admin: true` 를 부여하면 활성화됩니다.

- **통계** (사이드바 "통계" 버튼) — 오늘 쿼리 수·성공률, 최근 30일 일자별 표, 서비스별 분포가 한 화면에. `log/stats.json` 을 그대로 읽어 보여 줍니다.
- **Claude CLI 관리** (헤더 "Claude CLI 열기" 버튼) — 브라우저 안에서 진짜 터미널(xterm.js)이 떠 서버의 `claude` CLI에 직접 접근. 토큰이 소진되거나 다른 계정으로 바꿔야 할 때 `/login` 으로 재인증 가능 (**서버 재시작 불필요**). OAuth URL을 새 탭에서 열어 로그인 → 인증 코드를 모달 터미널에 Cmd+V / Ctrl+V 로 붙여넣기 → 헤더가 자동으로 녹색(● Claude 연결됨)으로 전환.

#### 로그
`log/` 디렉터리에 자동 기록됩니다 (디렉터리 자동 생성).

- **`log/queries.jsonl`** — 질문 1건당 JSON Lines 한 줄. 시각·유저·서비스·질문 원문·실행된 SQL·소요 시간 등이 담깁니다. 50MB 를 넘으면 `.1` ~ `.5` 로 자동 회전 (기본 5개 보관).
- **`log/stats.json`** — 날짜별 누적 통계(총 질문 수·성공·실패·서비스별 카운트). 관리자 통계 모달이 이 파일을 읽어 보여 줍니다.

```json
{"ts":"2026-05-24T16:18:03+09:00","user":"admin","service":"order","question":"...","answered":true,"iterations":2,"elapsed_ms":4123,"queries":[{"sql":"SELECT ...","rows":42,"ms":88,"error":null}],"answer_chars":850}
```
