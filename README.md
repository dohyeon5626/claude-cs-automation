# CS Automation

![License](https://img.shields.io/github/license/dohyeon5626/claude-cs-automation?style=flat&color=green) ![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat&logo=python&logoColor=white) ![Powered by Claude](https://img.shields.io/badge/Powered_by-Claude-cc785c?style=flat) ![Tailwind](https://img.shields.io/badge/Tailwind-CDN-38B2AC?style=flat&logo=tailwindcss&logoColor=white)
<br/><br/>

CS(고객서비스) 담당자가 **웹 브라우저에서 자연어로 질문**하면, 개발자 PC의 Claude가 데이터베이스를 조회해 결과를 Markdown으로 정리해 주는 시스템입니다.<br/>
예) "어제 주문 중 배송 안 된 건 몇 개야?" → Claude가 알아서 SQL을 만들어 조회 → 표로 정리해 답변<br/>
CS 담당자는 별도 설치 없이 같은 WiFi에서 브라우저로 접속해 사용할 수 있습니다.<br/>
<br/>

---

### 어떻게 동작하나
CS 담당자의 자연어 질문을 받아, 개발자 PC의 Claude CLI가 해당 서비스의 GitHub 레포 코드와 DB 스키마를 살펴본 뒤 SELECT 쿼리를 만들고, 서버가 안전 검증 후 실행해 결과를 정리해 줍니다.<br/>
데이터를 바꾸는 쿼리(INSERT/UPDATE/DELETE 등)는 **절대 실행되지 않습니다.**
```
1. 흐름도
- CS 담당자 (웹 브라우저)
- ↓ 질문
- 서버 (개발자 PC) ─ Claude CLI ─ GitHub 레포 (코드/문서 파악)
- ↓
- MySQL DB (SELECT 전용)
- ↓ 결과
- 정리된 Markdown 답변 → 웹 브라우저
```

### 서비스
이 시스템은 여러 서비스를 다룰 수 있고, 서비스 하나는 곧 "조회 대상 하나"입니다.<br/>
각 서비스는 자기만의 **GitHub 레포**와 (선택적으로) **데이터베이스**를 가집니다. 사용자마다 어떤 서비스에 접근할 수 있는지도 따로 정합니다.
```
1. 서비스 단위로 분리되는 항목
- GitHub 레포 (필수): Claude 가 도메인 파악에 사용
- 데이터베이스 (선택): 없으면 레포 문서만으로 답변
- 로고 (선택): 비우면 이름 첫 글자 아이콘 자동 생성

2. 사용자 단위로 부여되는 항목
- 접근 가능한 서비스 id 목록 (["*"] 이면 전체)
```

### 준비물 (서버 운영자 PC)
서버는 개발자 PC에서 실행됩니다. 아래 항목이 모두 준비되어야 시작되며, 누락되면 서버가 시작되지 않고 어디가 문제인지 알려 줍니다.<br/>
CS 담당자는 브라우저만 있으면 되며, 아무것도 설치할 필요가 없습니다.
```
1. 필수 환경
- Python 3.11+
- Git: git config --global user.name / user.email 설정 필요
- Claude CLI: Claude Code 설치 후 로그인. 'claude' 가 PATH 에 있어야 함

2. 서비스별 접근
- MySQL: 각 서비스의 DB 계정으로 접속 가능 (DB 가 있는 서비스에 한함)
- GitHub: git clone/pull 이 비대화식으로 동작 (Private 레포는 SSH 키 또는 토큰)
```

### 설정 (config.yml)
모든 설정은 `config.yml` 하나로 끝납니다. `config-example.yml` 을 복사해서 시작하세요.
> [config-example.yml](config-example.yml)
```yaml
server:
  port: 8765

brand:
  name: "CS Automation"
  logo: ""                  # 이미지 URL 또는 로컬 경로. 비우면 이름 첫 글자 표시

claude:
  model: "sonnet"
  # path: "/path/to/claude" # 'claude' 가 PATH 에 없을 때만

services:
  - id: "order"
    name: "주문 서비스"
    description: "주문 조회 및 배송 상태 확인"
    logo: ""                # 서비스별 로고 (선택). URL 또는 로컬 경로
    github:
      url: "https://github.com/yourorg/order-service"
      branch: "main"
    database:               # 선택 사항 — 없으면 레포 문서만 사용
      host: "localhost"
      port: 3306
      name: "order_db"
      user: "readonly_user"
      password: "db_password"

users:
  - id: "admin"
    password: "changeme"
    name: "관리자"
    services: ["*"]         # ["*"] = 모든 서비스 접근 가능
```

### 실행
가상환경(venv) 안에서 실행하는 걸 권장합니다.
```bash
1. 가상환경 만들기 (최초 1회)
- python -m venv .venv

2. 가상환경 활성화 (터미널 열 때마다)
- source .venv/bin/activate          # macOS / Linux
- .venv\Scripts\Activate.ps1         # Windows PowerShell

3. 의존성 설치 (최초 1회)
- pip install -r requirements.txt

4. 서버 실행
- python run.py
```
서버가 켜지면 시작 검증(Git · Claude CLI · 서비스별 DB/레포)을 거친 뒤 **접속 주소를 콘솔에 출력합니다.**
```
1. 출력 예시
- 이 PC에서:           http://localhost:8765
- 같은 WiFi의 다른 PC: http://192.168.0.15:8765
```

### CS 담당자 접속하기
서버와 **같은 WiFi(같은 네트워크)** 에 연결된 PC라면 누구나 접속할 수 있습니다.<br/>
서버 운영자는 콘솔에 표시된 LAN IP 주소를 동료에게 알려주기만 하면 됩니다.
```
1. 접속 순서
- 브라우저에서 http://<서버 PC의 IP주소>:8765 입력
- 발급받은 아이디/비밀번호로 로그인 (로그인은 새로고침해도 유지됨)
- 사이드바에서 담당 서비스 선택 (자동으로 마지막 사용 서비스 선택됨)
- 자연어로 질문 (Enter 전송 · Shift+Enter 줄바꿈)

2. 접속이 안 될 때
- 서버 PC 와 같은 WiFi 에 연결되어 있는지 확인
- 서버 PC 의 방화벽이 포트(8765) 를 막고 있지 않은지 확인
```

### REST API
웹 페이지 외에 프로그램에서 직접 호출할 수도 있습니다.
```bash
1. 로그인 → 토큰 발급
- curl -X POST http://SERVER:8765/api/login \
    -H "Content-Type: application/json" \
    -d '{"user_id":"cs001","password":"changeme"}'

2. 질문 (발급받은 토큰 사용)
- curl -X POST http://SERVER:8765/api/query \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer <발급받은_토큰>" \
    -d '{"service_id":"order","message":"오늘 들어온 주문 수는?"}'

3. 실시간 처리 진행 상황까지 보려면 /ws WebSocket 사용 (웹 페이지가 쓰는 방식)
```

### 안전장치
Claude 의 판단(소프트) + 서버의 정규식 검증(하드) + DB 권한(최종) **3중 구조**로 안전을 확보합니다.<br/>
Claude 가 실수로 위험한 쿼리를 만들어도 서버 코드가 막고, 그것까지 뚫려도 DB 계정 권한이 막습니다.
```
1. 인증·권한
- 로그인 + 사용자별 서비스 접근 권한 검사

2. Claude 1차 판단
- SELECT 외 쿼리는 만들지 않도록 시스템 프롬프트에서 규칙 명시
- 민감 정보(비밀번호, 카드번호 등) 조회/노출 금지
- 과도한 요청(전체 테이블 덤프 등) 거절

3. 서버 강제 검증
- SELECT 가 아닌 쿼리는 코드로 차단 (정규식)
- LIMIT 이 없으면 자동으로 LIMIT 100 추가
- 루프 최대 12회, 결과 크기 20KB 제한

4. 최종 방어선
- config.yml 의 DB 계정을 read-only MySQL 사용자로 권장
```

### 폴더 구조
```
1. 프로젝트 루트
- run.py            실행 진입점 (python run.py)
- config.yml        설정 파일
- requirements.txt  의존성

2. 애플리케이션 코드 (src/)
- main.py        시작 검증 + 서버 실행
- config.py      config.yml 읽기
- auth.py        로그인/인증
- database.py    MySQL 조회 (서비스별)
- repository.py  GitHub 레포 동기화 (서비스별)
- service.py     서비스 런타임
- agent.py       Claude 호출 및 질의 처리
- server.py      웹 서버 (페이지 · API · WebSocket)
- web/           웹 페이지 (HTML · CSS · JS)
```

### 문제 해결
```
1. 시작 검증 단계 오류
- Git 설정 오류:     git config --global user.name / user.email 확인
- DB 연결 실패:      해당 서비스의 database 설정, MySQL 실행 여부 확인
- GitHub 클론 실패:  레포 url/branch, Private 레포 인증(SSH 키/토큰) 확인
- Claude CLI 오류:   claude 설치 및 로그인 상태 확인

2. 사용 중 오류
- 웹 접속 안 됨:     같은 WiFi 여부, 콘솔의 IP/포트, 방화벽 확인
- 로그인 실패:       config.yml 의 users 항목, 아이디/비밀번호 확인
- 새 로고 안 바뀜:   브라우저 강력 새로고침 (Cmd+Shift+R 또는 Ctrl+Shift+R)
```

### 라이선스
MIT License — 자유롭게 사용, 수정, 배포할 수 있습니다.
