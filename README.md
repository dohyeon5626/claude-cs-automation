# CS Automation — Claude 기반 CS 데이터베이스 조회 시스템

CS(고객서비스) 담당자가 자연어로 질문하면 Claude AI가 MySQL 쿼리를 생성하고 결과를 Markdown으로 반환하는 데스크탑 + 서버 시스템입니다.

```
CS 담당자 (cs-desktop)  ←→  WebSocket  ←→  서버 (cs-server)  ←→  MySQL DB
                                                     ↕
                                             Claude AI (Anthropic)
                                                     ↕
                                             GitHub 레포 (스키마 참조)
```

---

## 구성

| 폴더 | 설명 | 언어 |
|------|------|------|
| `cs-desktop/` | CS 담당자용 PyQt6 데스크탑 앱 | Python |
| `cs-server/` | WebSocket 서버 + Claude + DB 처리 | Python |

---

## 동작 흐름

1. **데스크탑 앱 실행** → 서버 IP, 사용자 ID 설정 (최초 1회)
2. **서버 연결** → 서비스 목록 수신 → 서비스 선택
3. **질문 입력** → 서버로 전송
4. **서버 처리**:
   - Claude가 요청 유효성 검증 (SELECT 가능 여부, 안전성)
   - GitHub 레포의 스키마를 참조해 MySQL SELECT 쿼리 생성
   - 데이터베이스 조회
   - Claude가 결과를 Markdown으로 정리
5. **데스크탑 앱에 결과 표시**

---

## 요구 사항

- Python 3.11+
- MySQL / MariaDB
- Anthropic API Key ([발급](https://console.anthropic.com))
- Git (전역 설정 필요: `user.name`, `user.email`)
- GitHub 레포 (데이터베이스 스키마 `.sql` 파일 또는 Markdown 문서 포함)

---

## 서버 설치 및 실행

### 1. 의존성 설치

```bash
cd cs-server
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 설정 파일 작성

`cs-server/config.yml`을 열고 내용을 수정합니다:

```yaml
server:
  host: "0.0.0.0"   # 모든 IP에서 수신
  port: 8765

database:
  host: "localhost"
  port: 3306
  name: "your_database"
  user: "your_user"
  password: "your_password"

github:
  repo_url: "https://github.com/yourorg/yourrepo"
  branch: "main"
  local_path: "./repo"          # 서버가 레포를 클론할 로컬 경로

claude:
  api_key: "sk-ant-..."         # 환경변수 ANTHROPIC_API_KEY로 대체 가능
  model: "claude-sonnet-4-6"

services:
  - id: "order_inquiry"
    name: "주문 조회"
    description: "고객 주문 관련 정보를 조회합니다"
  - id: "customer_info"
    name: "고객 정보 조회"
    description: "고객 기본 정보를 조회합니다"
  # 원하는 서비스를 추가하세요
```

> **보안 팁**: API 키와 DB 패스워드는 환경변수로 관리하는 것을 권장합니다.
> ```bash
> export ANTHROPIC_API_KEY="sk-ant-..."
> export DB_PASSWORD="your_password"
> ```

### 3. GitHub 레포에 스키마 추가

서버가 참조할 레포에 `.sql` 또는 `.md` 파일로 스키마를 추가하세요:

```sql
-- schema.sql 예시
CREATE TABLE orders (
    id INT PRIMARY KEY,
    customer_id INT,
    status VARCHAR(20),    -- pending, shipped, delivered, cancelled
    created_at DATETIME
);

CREATE TABLE customers (
    id INT PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(200),
    created_at DATETIME
);
```

### 4. 서버 실행

```bash
cd cs-server
python main.py
```

시작 시 아래 3가지를 자동으로 검증합니다:
- Git 전역 설정 (`user.name`, `user.email`)
- GitHub 레포 clone/pull
- MySQL 연결

검증 실패 시 서버가 실행되지 않고 오류 메시지를 출력합니다.

---

## 데스크탑 앱 설치 및 실행

### 1. 의존성 설치

```bash
cd cs-desktop
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 실행

```bash
python main.py
```

**최초 실행 시** 서버 IP와 사용자 ID 입력 화면이 표시됩니다.  
이후 실행부터는 저장된 설정으로 자동 연결됩니다.

설정은 `~/.cs-desktop/settings.json`에 저장됩니다.

---

## 화면 구성

### 초기 설정 화면
- 서버 IP / 포트 / 사용자 ID 입력
- 저장하면 바로 서버에 연결 시도

### 서비스 선택 화면
- 서버에서 받아온 서비스 목록 표시
- 서비스를 선택하면 채팅 화면으로 이동

### 채팅 화면
- 자연어로 질문 입력
- Enter: 전송 / Shift+Enter: 줄바꿈
- 결과는 Markdown으로 렌더링되어 표시
- 헤더의 "서비스 변경" 버튼으로 서비스 재선택
- 헤더의 "설정" 버튼으로 서버 설정 변경

---

## WebSocket 메시지 프로토콜

서버와 데스크탑 앱 간의 메시지 형식입니다. 커스텀 클라이언트 개발 시 참고하세요.

### 클라이언트 → 서버

| type | 설명 | 필드 |
|------|------|------|
| `auth` | 사용자 인증 | `user_id` |
| `select_service` | 서비스 선택 | `service_id` |
| `query` | 질문 전송 | `message` |

### 서버 → 클라이언트

| type | 설명 | 필드 |
|------|------|------|
| `auth_required` | 인증 요청 | `message` |
| `auth_success` | 인증 성공 | `user_id`, `services[]` |
| `service_selected` | 서비스 선택 확인 | `service_id`, `service_name` |
| `status` | 처리 상태 메시지 | `message` |
| `response` | 최종 Markdown 응답 | `message` |
| `rejected` | 처리 불가 (Claude 판단) | `message` |
| `error` | 오류 | `message` |

---

## 보안 고려사항

- 서버는 **SELECT 쿼리만** 실행합니다 (INSERT/UPDATE/DELETE/DROP 불가)
- LIMIT이 없는 쿼리에는 자동으로 `LIMIT 100`이 추가됩니다
- Claude가 요청의 적합성을 1차 판단하여 과도하거나 부적절한 요청을 차단합니다
- 서버는 내부 네트워크에서만 운영하는 것을 권장합니다

---

## 트러블슈팅

**서버: Git 설정 오류**
```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

**서버: DB 연결 실패**  
`config.yml`의 `[database]` 섹션을 확인하고, MySQL이 실행 중인지 확인하세요.

**서버: GitHub 클론 실패**  
Private 레포라면 SSH 키 또는 Personal Access Token이 설정되어 있어야 합니다.

**데스크탑: 연결 실패**  
- 서버가 실행 중인지 확인
- 방화벽에서 포트(기본 8765)가 열려 있는지 확인
- 서버 IP와 포트가 정확한지 확인

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포하실 수 있습니다.
