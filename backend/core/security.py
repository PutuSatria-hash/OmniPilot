"""Authentication helpers for REST, WebSocket, and phone webhook endpoints."""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, WebSocket, status

from backend.core.config import Settings, get_settings


def _verify_token(candidate: Optional[str], expected: str) -> bool:
    if not candidate or not expected:
        return False
    return secrets.compare_digest(candidate.strip(), expected.strip())


async def require_auth(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate API authentication via Bearer header, X-API-Key, or query token."""
    bearer_token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[7:].strip()

    for candidate in (bearer_token, x_api_key, token):
        if _verify_token(candidate, settings.api_auth_token):
            return candidate or ""

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token autentikasi tidak valid atau tidak ditemukan.",
    )


async def verify_websocket_token(websocket: WebSocket, settings: Settings) -> bool:
    """Validate token from WebSocket query string or headers."""
    token = websocket.query_params.get("token") or websocket.headers.get("x-api-key")
    auth_header = websocket.headers.get("authorization")
    if not token and auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    return _verify_token(token, settings.api_auth_token)
