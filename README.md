# Claude CS Automation

![License](https://img.shields.io/github/license/dohyeon5626/claude-cs-automation?style=flat&color=green) ![GitHub Tag](https://img.shields.io/github/v/tag/dohyeon5626/claude-cs-automation?style=flat&color=green) ![Powered by Claude](https://img.shields.io/badge/Powered_by-Claude-cc785c?style=flat)
<br/>

<img width="100%" align=center alt="readme" src="https://github.com/user-attachments/assets/426feddd-1b17-4142-ac16-95b373801792">
<br/><br/>

CS 담당자가 질문하면 Claude가 GitHub 코드와 데이터베이스를 조회해 답해 주는 프로젝트<br/>
예) "어제 주문 중 배송 안 된 건 몇 개야?" → SQL 자동 생성 → DB 조회 → 표로 정리해 답변<br/>
예) "이 기능 어떻게 설정돼 있지?" → 레포 코드 탐색 → 답변<br/>
개발자가 매번 사소한 질문에 답하느라 드는 시간을 줄이려고 만들었습니다. 이 레포지토리를 다운받아 설정한 뒤, 회사에서 일할 때 자기 PC에 켜 두기만 하면 됩니다.<br/>


---

### 동작 방식
질문이 들어오면 Claude가 SQL을 만들고, 서버가 안전 검증 후 실행해 결과를 정리합니다.<br/>
데이터를 바꾸는 쿼리(INSERT/UPDATE/DELETE)는 **절대 실행되지 않습니다.**
```
- CS 담당자 (웹 브라우저)
- ↓ 질문
- 서버 (개발자 PC) ─ Claude CLI ─ GitHub 레포 (코드 파악)
- ↓
- MySQL DB (SELECT만)
- ↓ 결과
- Markdown 답변 → 웹 브라우저
```

### 서비스
"서비스 하나 = 조회 대상 하나" 입니다. 서비스마다 GitHub 레포와 데이터베이스를 따로 둡니다.
```
- GitHub 레포 (필수)   Claude가 코드를 읽어 도메인 파악에 사용
- 데이터베이스 (선택)  없으면 레포 문서만으로 답변
- 로고 (선택)         비우면 이름 첫 글자 아이콘 자동 생성
- 사용자 권한         서비스마다 누가 접근할 수 있는지 지정
```

### 준비물 (서버 운영자 PC)
서버는 개발자 PC에서 실행합니다. 아래가 준비되어 있지 않으면 서버가 시작되지 않고, 어디가 문제인지 알려 줍니다.<br/>
CS 담당자는 브라우저만 있으면 됩니다.
```
- Python 3.11+
- Git              git config --global user.name / user.email 설정
- Claude CLI       Claude Code 설치. 'claude'가 PATH에 있어야 함 (로그아웃 상태여도
                   서버는 시작되고, 관리자가 웹 UI에서 로그인 가능)
- MySQL 접근       (DB가 있는 서비스에 한함) 서비스별 계정으로 접속 가능
- GitHub 레포 접근  git clone/pull이 비대화식으로 동작 (Private은 SSH 키/토큰)
```
MySQL 계정은 **read-only 권한**으로 만들어 두는 걸 권장합니다. SELECT 외 쿼리는 서버에서 이미 차단되지만, DB 계정 자체가 읽기 전용이면 마지막 방어선이 됩니다.

### 설정 (config.yml)
`config.yml` 한 파일에서 아래 다섯 가지를 설정합니다.
```
- server     웹 접속 포트
- brand      앱 이름·로고 (선택)
- claude     Claude CLI 모델·경로
- services   조회 대상 — GitHub 레포 필수, DB·로고 선택
- users      로그인 계정과 서비스별 접근 권한
```
예시:
```yaml
server:
  port: 8765

claude:
  model: "sonnet"

services:
  - id: "order"
    name: "주문 서비스"
    github:
      url: "https://github.com/yourorg/order-service"
      branch: "main"
    database:
      host: "localhost"
      port: 3306
      name: "order_db"
      user: "readonly_user"
      password: "db_password"

users:
  - id: "admin"
    password: "changeme"
    services: ["*"]
    admin: true        # 통계·Claude CLI 관리 권한 부여 (선택)
```
brand, 서비스별 logo, 사용자별 services 권한, admin 플래그 등 세부 옵션은 `config.yml`의 주석에 정리되어 있습니다.

### 실행
가상환경(venv) 안에서 실행하는 걸 권장합니다.
```
- python -m venv .venv                  # 최초 1회
- source .venv/bin/activate             # 매번 (macOS/Linux)
- .venv\Scripts\Activate.ps1            # 매번 (Windows PowerShell)
- pip install -r requirements.txt       # 최초 1회
- python run.py                         # 서버 시작
```
시작 검증(Git 설정 · Claude CLI · 서비스별 GitHub 레포·DB)을 통과하면 콘솔에 접속 주소가 출력됩니다. 종료는 Ctrl+C.

### CS 담당자 접속
서버와 **같은 WiFi**에 있는 PC라면 누구나 브라우저로 접속할 수 있습니다.<br/>
운영자가 서버 콘솔에 표시되는 주소를 동료에게 알려주기만 하면 됩니다.
```
- 주소창에 http://<서버 PC IP>:8765 입력
- 로그인 (한 번 하면 새로고침해도 유지됨)
- 사이드바에서 서비스 선택 (마지막 사용 서비스 자동 선택됨)
- Enter 전송 · Shift+Enter 줄바꿈
```
서버를 실행하면 콘솔에 `http://192.168.x.x:8765` 형태로 IP가 자동 표시됩니다. 그 주소를 그대로 동료에게 알려주면 됩니다. 수동으로 확인하고 싶다면:
```
- macOS    터미널에서  ipconfig getifaddr en0
- Windows  cmd 에서   ipconfig  → "IPv4 주소" 항목
- Linux    터미널에서  hostname -I
```

접속 안 될 때 → 같은 WiFi인지, 방화벽이 포트(8765) 막고 있지 않은지 확인.

### 관리자 기능
`config.yml`의 사용자에 `admin: true` 를 부여하면 두 가지가 활성화됩니다.

**통계 (사이드바 "통계" 버튼)**
오늘 쿼리 수·성공률, 최근 30일 일자별 표, 서비스별 분포가 한 화면에 정리됩니다. `log/stats.json`을 그대로 읽어 보여 주는 식이라 별도 DB가 필요 없습니다.

**Claude CLI 관리 (헤더 우측 "Claude CLI 열기" 버튼)**
브라우저 안에서 진짜 터미널(xterm.js)이 떠서 서버의 `claude` CLI에 그대로 접근할 수 있습니다. 토큰이 소진되거나 다른 계정으로 바꿔야 할 때 `/login` 으로 재인증 가능 — **서버 재시작 불필요**.
```
- 모달의 OAuth URL을 클릭 → 새 탭에서 Anthropic 로그인
- 발급된 인증 코드를 모달 터미널에 Cmd+V / Ctrl+V 로 붙여넣기
- 인증 완료 시 헤더 표시가 자동으로 녹색(● Claude 연결됨)으로 전환
```

### 로그
질문 1건당 한 줄씩 `log/queries.jsonl` 에 JSON Lines 로 기록됩니다 (디렉터리 자동 생성). 한 줄에 시각·유저·서비스·질문 원문·실행된 SQL·소요 시간이 모두 담깁니다.
```json
{"ts":"2026-05-24T16:18:03+09:00","user":"admin","service":"order","question":"...","answered":true,"iterations":2,"elapsed_ms":4123,"queries":[{"sql":"SELECT ...","rows":42,"ms":88,"error":null}],"answer_chars":850}
```
같은 디렉터리의 `log/stats.json` 에는 날짜별 누적 통계(총 질문 수·성공·실패·서비스별 카운트)가 함께 갱신되며, 관리자 통계 모달이 이 파일을 읽어 보여 줍니다.
```json
{"2026-05-24": {"total": 10, "answered": 8, "failed": 2, "by_service": {"order": 7, "knowledge": 3}}}
```
`queries.jsonl` 은 50MB를 넘으면 `.1` ~ `.5` 로 자동 회전됩니다 (기본 5개 보관).
