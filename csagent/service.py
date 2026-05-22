from dataclasses import dataclass

from .config import ServiceConfig
from .database import Database


@dataclass
class Service:
    """
    A ready-to-use service: its config bundled with a live database
    connection. Built once at startup, after validation passes.
    """

    config: ServiceConfig
    database: Database

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def description(self) -> str:
        return self.config.description
