"""JWT token utilities for MongoDB-backed users."""
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings


def _secret():
    return settings.SECRET_KEY


def generate_tokens(user) -> tuple[str, str]:
    """Return (access_token, refresh_token) for a MongoUser."""
    now = datetime.now(timezone.utc)

    access_payload = {
        'token_type': 'access',
        'user_id': user.id_str,
        'username': user.username,
        'role': user.role,
        'iat': now,
        'exp': now + timedelta(hours=getattr(settings, 'JWT_ACCESS_HOURS', 8)),
    }
    refresh_payload = {
        'token_type': 'refresh',
        'user_id': user.id_str,
        'iat': now,
        'exp': now + timedelta(days=getattr(settings, 'JWT_REFRESH_DAYS', 7)),
    }

    access = jwt.encode(access_payload, _secret(), algorithm='HS256')
    refresh = jwt.encode(refresh_payload, _secret(), algorithm='HS256')
    return access, refresh


def decode_access_token(token: str) -> dict:
    """Decode and validate an access token. Raises jwt.* on failure."""
    payload = jwt.decode(token, _secret(), algorithms=['HS256'])
    if payload.get('token_type') != 'access':
        raise jwt.InvalidTokenError('Not an access token.')
    return payload


def decode_refresh_token(token: str) -> dict:
    """Decode and validate a refresh token."""
    payload = jwt.decode(token, _secret(), algorithms=['HS256'])
    if payload.get('token_type') != 'refresh':
        raise jwt.InvalidTokenError('Not a refresh token.')
    return payload
