import yaml
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class ServiceConfig:
    id: str
    name: str
    description: str


@dataclass
class UserConfig:
    id: str
    password: str
    name: str
    services: List[str]  # allowed service ids, or ["*"] for all


@dataclass
class AppConfig:
    server_host: str
    server_port: int
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    github_repo_url: str
    github_branch: str
    github_local_path: str
    claude_model: str
    services: List[ServiceConfig] = field(default_factory=list)
    users: List[UserConfig] = field(default_factory=list)


def load_config(path: str = "config.yml") -> AppConfig:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Edit config.yml to fill in your settings."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    _validate_required_keys(raw)

    services = [
        ServiceConfig(id=str(s["id"]), name=str(s["name"]), description=str(s["description"]))
        for s in raw.get("services", [])
    ]

    users = []
    for u in raw.get("users", []):
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

    # Environment variable takes priority over YAML for the DB password
    db_password = os.environ.get("DB_PASSWORD") or raw["database"]["password"]

    claude_section = raw.get("claude") or {}

    config = AppConfig(
        server_host=raw["server"]["host"],
        server_port=int(raw["server"]["port"]),
        db_host=raw["database"]["host"],
        db_port=int(raw["database"]["port"]),
        db_name=raw["database"]["name"],
        db_user=raw["database"]["user"],
        db_password=db_password,
        github_repo_url=raw["github"]["repo_url"],
        github_branch=raw["github"]["branch"],
        github_local_path=raw["github"]["local_path"],
        claude_model=str(claude_section.get("model", "") or ""),
        services=services,
        users=users,
    )

    _validate_semantics(config)
    return config


def _validate_required_keys(raw: dict):
    required = {
        "server": ["host", "port"],
        "database": ["host", "port", "name", "user", "password"],
        "github": ["repo_url", "branch", "local_path"],
    }
    for section, keys in required.items():
        if section not in raw:
            raise ValueError(f"Missing config section: [{section}]")
        for key in keys:
            if key not in raw[section]:
                raise ValueError(f"Missing config key: [{section}].{key}")

    if not raw.get("services"):
        raise ValueError("[services] 섹션에 최소 1개의 서비스가 필요합니다.")
    if not raw.get("users"):
        raise ValueError("[users] 섹션에 최소 1명의 사용자가 필요합니다.")

    for u in raw["users"]:
        for key in ("id", "password"):
            if key not in u:
                raise ValueError(f"[users] 항목에 '{key}'가 없습니다.")


def _validate_semantics(config: AppConfig):
    """Check that each user's services reference real service ids."""
    service_ids = {s.id for s in config.services}
    for user in config.users:
        for sid in user.services:
            if sid != "*" and sid not in service_ids:
                raise ValueError(
                    f"사용자 '{user.id}'가 존재하지 않는 서비스 '{sid}'를 참조합니다. "
                    f"config.yml의 [services]를 확인하세요."
                )
