import json
import os
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class Settings:
    server_ip: str = ""
    server_port: int = 8765
    user_id: str = ""

    def is_configured(self) -> bool:
        return bool(self.server_ip.strip() and self.user_id.strip())

    @property
    def ws_url(self) -> str:
        return f"ws://{self.server_ip}:{self.server_port}"


_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".cs-desktop", "settings.json")


def load_settings() -> Settings:
    if not os.path.exists(_CONFIG_PATH):
        return Settings()
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Settings(
            server_ip=data.get("server_ip", ""),
            server_port=int(data.get("server_port", 8765)),
            user_id=data.get("user_id", ""),
        )
    except Exception:
        return Settings()


def save_settings(settings: Settings):
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
