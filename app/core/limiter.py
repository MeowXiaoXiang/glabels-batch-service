"""Build independent in-memory submission limits for each application."""

from slowapi import Limiter
from slowapi.util import get_remote_address


def create_limiter() -> Limiter:
    return Limiter(key_func=get_remote_address, default_limits=[])
