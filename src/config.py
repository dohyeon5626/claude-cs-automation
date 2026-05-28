import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


# ${VAR} or ${VAR:-default} — docker-compose / bash-ish syntax.
# Only ALLCAPS-style names so we don't accidentally chew through arbitrary $ in
# config values; if you need a literal "${...}" wrap the value in single quotes.
_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")


def _load_dotenv(path: str = ".env") -> None:
    """
    Read KEY=VALUE pairs from .env into os.environ. OS env wins — values
    already exported in the shell are NOT overwritten. Quiet no-op if the
    file doesn't exist. Quotes around values are stripped; comments and
    blank lines are ignored. No shell expansion.
    """
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            os.environ.setdefault(key, val)


def _substitute_env(text: str) -> str:
    """
    Replace ${VAR} and ${VAR:-default} occurrences with env var values.
    Raises ValueError listing every missing var if any reference is
    unresolved (no env value, no default) — better to fail loudly at
    startup than to feed empty passwords into the DB driver.
    """
    missing = []

    def repl(m):
        name = m.group(1)
        default = m.group(2)
        val = os.environ.get(name)
        if val not in (None, ""):
            return val
        if default is not None:
            return default
        missing.append(name)
        return m.group(0)  # leave untouched; will fail below

    result = _ENV_VAR_RE.sub(repl, text)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise ValueError(
            f"config.yml 이 참조하는 환경변수가 비어 있습니다: {names}\n"
            "  - 셸에서 'export NAME=값' 으로 지정하거나\n"
            "  - 프로젝트 루트의 .env 파일에 'NAME=값' 한 줄을 추가하거나\n"
            "  - config.yml 에서 '${NAME:-기본값}' 형태로 기본값을 두세요."
        )
    return result


@dataclass
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str
    kind: str = "mysql"  # mysql | postgres | oracle


@dataclass
class GithubConfig:
    url: str
    branch: str


@dataclass
class ServiceConfig:
    id: str
    name: str
    description: str
    github: GithubConfig
    database: Optional[DatabaseConfig] = None  # 데이터베이스가 없는 서비스도 허용
    logo: str = ""  # 이미지 URL 또는 로컬 경로. 비어 있으면 파스텔 첫 글자 아이콘 자동 생성

    @property
    def repo_path(self) -> str:
        """Local directory where this service's repo is cloned."""
        return os.path.abspath(os.path.join("repos", self.id))


@dataclass
class UserConfig:
    id: str
    password: str
    name: str
    services: List[str]  # allowed service ids, or ["*"] for all
    admin: bool = False  # may manage Claude CLI login/logout from the web UI


@dataclass
class AppConfig:
    port: int
    claude_model: str
    claude_binary: str  # 'claude' (PATH 사용) 또는 절대 경로
    brand_name: str     # 사이드바/로그인에 표시되는 이름
    brand_logo: str     # 이미지 URL 또는 로컬 경로. 비어 있으면 brand_name 첫 글자가 표시됨
    services: List[ServiceConfig] = field(default_factory=list)
    users: List[UserConfig] = field(default_factory=list)


def load_config(path: str = "config.yml") -> AppConfig:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"설정 파일을 찾을 수 없습니다: {path}\n"
            "config.yml 을 만들고 설정을 입력하세요."
        )

    # Read as text first so we can substitute ${VAR} references against the
    # combined OS env + .env file before YAML parsing.
    _load_dotenv()
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    text = _substitute_env(text)
    raw = yaml.safe_load(text) or {}

    _validate(raw)

    services = [_parse_service(s) for s in raw["services"]]

    users = []
    for u in raw["users"]:
        svc = u.get("services", [])
        if isinstance(svc, str):
            svc = [svc]
        users.append(
            UserConfig(
                id=str(u["id"]),
                password=str(u["password"]),
                name=str(u.get("name", u["id"])),
                services=[str(x) for x in svc],
                admin=bool(u.get("admin", False)),
            )
        )

    claude_section = raw.get("claude") or {}
    brand_section = raw.get("brand") or {}

    return AppConfig(
        port=int(raw["server"]["port"]),
        claude_model=str(claude_section.get("model", "") or ""),
        claude_binary=str(claude_section.get("path", "") or "claude"),
        brand_name=str(brand_section.get("name", "") or "CS Automation"),
        brand_logo=str(brand_section.get("logo", "") or ""),
        services=services,
        users=users,
    )


def _parse_service(s: dict) -> ServiceConfig:
    gh = s["github"]
    database = None
    if s.get("database"):
        db = s["database"]
        database = DatabaseConfig(
            host=str(db["host"]),
            port=int(db["port"]),
            name=str(db["name"]),
            user=str(db["user"]),
            password=str(db["password"]),
            kind=str(db.get("kind", "mysql") or "mysql").lower(),
        )

    return ServiceConfig(
        id=str(s["id"]),
        name=str(s["name"]),
        description=str(s.get("description", "")),
        github=GithubConfig(url=str(gh["url"]), branch=str(gh["branch"])),
        database=database,
        logo=str(s.get("logo", "") or ""),
    )


def _validate(raw: dict):
    if "server" not in raw or "port" not in raw["server"]:
        raise ValueError("[server].port 가 없습니다.")

    if not raw.get("services"):
        raise ValueError("[services] 섹션에 최소 1개의 서비스가 필요합니다.")
    if not raw.get("users"):
        raise ValueError("[users] 섹션에 최소 1명의 사용자가 필요합니다.")

    service_ids = set()
    for s in raw["services"]:
        for key in ("id", "name", "github"):
            if key not in s:
                raise ValueError(f"[services] 항목에 '{key}' 가 없습니다.")
        sid = str(s["id"])
        if sid in service_ids:
            raise ValueError(f"서비스 id가 중복되었습니다: '{sid}'")
        service_ids.add(sid)

        # database 는 선택 사항. 있을 때만 키 검사.
        if s.get("database"):
            for key in ("host", "port", "name", "user", "password"):
                if key not in s["database"]:
                    raise ValueError(
                        f"서비스 '{sid}'의 database 에 '{key}' 가 없습니다."
                    )
            kind = str(s["database"].get("kind", "mysql") or "mysql").lower()
            if kind not in {"mysql", "postgres", "postgresql", "pg", "oracle"}:
                raise ValueError(
                    f"서비스 '{sid}'의 database.kind 가 잘못되었습니다: '{kind}'. "
                    "mysql / postgres / oracle 중에서 선택하세요."
                )

        for key in ("url", "branch"):
            if key not in s["github"]:
                raise ValueError(f"서비스 '{sid}'의 github 에 '{key}' 가 없습니다.")

    user_ids = set()
    for u in raw["users"]:
        for key in ("id", "password"):
            if key not in u:
                raise ValueError(f"[users] 항목에 '{key}' 가 없습니다.")
        uid = str(u["id"])
        if uid in user_ids:
            raise ValueError(f"사용자 id가 중복되었습니다: '{uid}'")
        user_ids.add(uid)
        svc = u.get("services", [])
        if isinstance(svc, str):
            svc = [svc]
        for sid in svc:
            if str(sid) != "*" and str(sid) not in service_ids:
                raise ValueError(
                    f"사용자 '{uid}'가 존재하지 않는 서비스 '{sid}'를 참조합니다."
                )
