import secrets
from typing import Dict, List, Optional

from .config import ServiceConfig, UserConfig


class Authenticator:
    """
    Authenticates users against the config.yml user list and issues
    in-memory session tokens. Tokens are lost on server restart.
    """

    def __init__(self, users: List[UserConfig], services: List[ServiceConfig]):
        self._users: Dict[str, UserConfig] = {u.id: u for u in users}
        self._services: Dict[str, ServiceConfig] = {s.id: s for s in services}
        self._tokens: Dict[str, str] = {}  # token -> user_id

    def login(self, user_id: str, password: str) -> Optional[str]:
        """Validate credentials. Returns a new token on success, else None."""
        user = self._users.get(user_id)
        if user is None:
            return None
        if not secrets.compare_digest(user.password, password):
            return None
        token = secrets.token_urlsafe(32)
        self._tokens[token] = user.id
        return token

    def user_for_token(self, token: str) -> Optional[UserConfig]:
        if not token:
            return None
        user_id = self._tokens.get(token)
        if user_id is None:
            return None
        return self._users.get(user_id)

    def logout(self, token: str):
        self._tokens.pop(token, None)

    def allowed_services(self, user: UserConfig) -> List[ServiceConfig]:
        """Resolve the list of services a user may access."""
        if "*" in user.services:
            return list(self._services.values())
        return [self._services[sid] for sid in user.services if sid in self._services]

    def can_access(self, user: UserConfig, service_id: str) -> bool:
        if service_id not in self._services:
            return False
        if "*" in user.services:
            return True
        return service_id in user.services
