from dataclasses import dataclass
from typing import Optional

from .config import ServiceConfig
from .database import Database


@dataclass
class Service:
    """
    A ready-to-use service: its config bundled with a live database
    connection (if the service has one). Built once at startup, after
    validation passes.
    """

    config: ServiceConfig
    database: Optional[Database] = None  # None 이면 DB 없는 서비스

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def description(self) -> str:
        return self.config.description
