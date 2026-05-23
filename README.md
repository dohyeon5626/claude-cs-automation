# CS Automation

![License](https://img.shields.io/github/license/dohyeon5626/claude-cs-automation?style=flat&color=green) ![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat&logo=python&logoColor=white) ![Powered by Claude](https://img.shields.io/badge/Powered_by-Claude-cc785c?style=flat) ![Tailwind](https://img.shields.io/badge/Tailwind-CDN-38B2AC?style=flat&logo=tailwindcss&logoColor=white)
<br/>

CS 담당자가 **웹에서 자연어로 질문**하면, Claude 가 깃허브 코드와 데이터베이스를 조회해 답을 정리해 주는 시스템입니다.<br/>
예) "어제 주문 중 배송 안 된 건 몇 개야?" → SQL 자동 생성 → DB 조회 → 표로 정리해 답변<br/>
예) "이 기능 어떻게 설정돼 있지?" → 레포 코드 탐색 → 답변<br/>
개발자가 매번 사소한 질문에 답하느라 드는 시간을 줄이려고 만들었습니다. 회사에서 일할 때 자기 PC 에 켜 두기만 하면 됩니다.<br/>


---

### 동작 방식
질문이 들어오면 Claude 가 SQL 을 만들고, 서버가 안전 검증 후 실행해 결과를 정리합니다.<br/>
데이터를 바꾸는 쿼리(INSERT/UPDATE/DELETE)는 **절대 실행되지 않습니다.**
```
- CS 담당자 (웹 브라우저)
- ↓ 질문
- 서버 (개발자 PC) ─ Claude CLI ─ GitHub 레포 (코드 파악)
- ↓
- MySQL DB (SELECT 만)
- ↓ 결과
- Markdown 답변 → 웹 브라우저
```

### 서비스
"서비스 하나 = 조회 대상 하나" 입니다. 서비스마다 GitHub 레포와 데이터베이스를 따로 둡니다.
```
- GitHub 레포 (필수)   Claude 가 코드를 읽어 도메인 파악에 사용
- 데이터베이스 (선택)  없으면 레포 문서만으로 답변
- 로고 (선택)         비우면 이름 첫 글자 아이콘 자동 생성
- 사용자 권한         서비스마다 누가 접근할 수 있는지 지정
```

### 준비물 (서버 운영자 PC)
서버는 개발자 PC 에서 실행합니다. 아래가 준비되어 있지 않으면 서버가 시작되지 않고, 어디가 문제인지 알려 줍니다.<br/>
CS 담당자는 브라우저만 있으면 됩니다.
```
- Python 3.11+
- Git              git config --global user.name / user.email 설정
- Claude CLI       Claude Code 설치 + 로그인. 'claude' 가 PATH 에 있어야 함
- MySQL 접근       (DB 가 있는 서비스에 한함) 서비스별 계정으로 접속 가능
- GitHub 레포 접근  git clone/pull 이 비대화식으로 동작 (Private 은 SSH 키/토큰)
```

### 설정 (config.yml)
모든 설정은 `config.yml` 하나에 들어갑니다. 
```yaml
server:
  port: 8765                # 웹 접속 포트

brand:
  name: "CS Automation"
  logo: ""                  # URL 또는 로컬 경로. 비우면 이름 첫 글자 표시

claude:
  model: "sonnet"
  # path: "/path/to/claude" # 'claude' 가 PATH 에 없을 때만

services:
  - id: "order"
    name: "주문 서비스"
    description: "주문 조회 및 배송 상태 확인"
    logo: ""                # 서비스별 로고 (선택)
    github:
      url: "https://github.com/yourorg/order-service"
      branch: "main"
    database:               # 선택 — 없으면 레포 문서만 사용
      host: "localhost"
      port: 3306
      name: "order_db"
      user: "readonly_user"
      password: "db_password"

users:
  - id: "admin"
    password: "changeme"
    name: "관리자"
    services: ["*"]         # ["*"] = 전체 접근
```

### CS 담당자 접속
서버와 **같은 WiFi** 에 있는 PC라면 누구나 브라우저로 접속할 수 있습니다.<br/>
운영자가 서버 콘솔에 표시되는 주소를 동료에게 알려주기만 하면 됩니다.
```
- 주소창에 http://<서버 PC IP>:8765 입력
- 로그인 (한 번 하면 새로고침해도 유지됨)
- 사이드바에서 서비스 선택 (마지막 사용 서비스 자동 선택됨)
- Enter 전송 · Shift+Enter 줄바꿈
```
접속 안 될 때 → 같은 WiFi 인지, 방화벽이 포트(8765) 막고 있지 않은지 확인.
