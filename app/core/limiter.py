# app/core/limiter.py
# Shared rate limiter instance for API endpoints

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
)

RATE_LIMIT = settings.RATE_LIMIT
