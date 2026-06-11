from typing import Optional

import httpx
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode

from app.config import get_settings

_jwks_cache: Optional[dict] = None


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            resp = await client.get(settings.cognito_jwks_url)
            resp.raise_for_status()
            _jwks_cache = resp.json()
    return _jwks_cache


async def verify_cognito_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        jwks = await _get_jwks()
        headers = jwt.get_unverified_headers(token)
        kid = headers["kid"]
        key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if key is None:
            return None
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.cognito_client_id,
            options={"verify_at_hash": False},
        )
        return payload
    except JWTError:
        return None
