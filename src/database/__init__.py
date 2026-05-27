"""
Database package — engine-agnostic adapters around a common Database ABC.

Use create_database(config) to get the right adapter for config.kind.
Adapters lazy-import their driver so only the ones you actually use need
to be pip-installed (see requirements-<engine>.txt).
"""

from .base import Database
from ..config import DatabaseConfig


def create_database(config: DatabaseConfig) -> Database:
    """
    Pick a Database adapter based on config.kind. Defaults to mysql when
    kind is missing so pre-existing config.yml files keep working.
    """
    kind = (getattr(config, "kind", None) or "mysql").lower().strip()

    if kind == "mysql":
        from .mysql import MySQLDatabase
        return MySQLDatabase(config)
    if kind in ("postgres", "postgresql", "pg"):
        from .postgres import PostgresDatabase
        return PostgresDatabase(config)
    if kind == "oracle":
        from .oracle import OracleDatabase
        return OracleDatabase(config)

    raise RuntimeError(
        f"지원하지 않는 데이터베이스 종류: '{kind}'. "
        "config.yml의 database.kind 는 mysql / postgres / oracle 중 하나여야 합니다."
    )


__all__ = ["Database", "create_database"]
