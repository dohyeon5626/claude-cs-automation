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
        ServiceConfig(id=s["id"], name=s["name"], description=s["description"])
        for s in raw.get("services", [])
    ]

    # Environment variable takes priority over YAML for the DB password
    db_password = os.environ.get("DB_PASSWORD") or raw["database"]["password"]

    claude_section = raw.get("claude") or {}

    return AppConfig(
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
    )


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
