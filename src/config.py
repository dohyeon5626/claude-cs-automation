import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str


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


@dataclass
class AppConfig:
    port: int
    claude_model: str
    claude_binary: str  # 'claude' (PATH 사용) 또는 절대 경로
    brand_name: str     # 사이드바/로그인에 표시되는 이름
    brand_mark: str     # 로고 그라데이션 안에 표시되는 글자 (1~3자 권장)
    services: List[ServiceConfig] = field(default_factory=list)
    users: List[UserConfig] = field(default_factory=list)


def load_config(path: str = "config.yml") -> AppConfig:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"설정 파일을 찾을 수 없습니다: {path}\n"
            "config.yml 을 만들고 설정을 입력하세요."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

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
            )
        )

    claude_section = raw.get("claude") or {}
    brand_section = raw.get("brand") or {}

    return AppConfig(
        port=int(raw["server"]["port"]),
        claude_model=str(claude_section.get("model", "") or ""),
        claude_binary=str(claude_section.get("path", "") or "claude"),
        brand_name=str(brand_section.get("name", "") or "CS Automation"),
        brand_mark=str(brand_section.get("mark", "") or "CS"),
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
        )

    return ServiceConfig(
        id=str(s["id"]),
        name=str(s["name"]),
        description=str(s.get("description", "")),
        github=GithubConfig(url=str(gh["url"]), branch=str(gh["branch"])),
        database=database,
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
