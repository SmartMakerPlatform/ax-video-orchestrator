import secrets

from fastapi import HTTPException, status


def require_api_key(provided: str | None, configured: str | None) -> None:
    if not configured or not provided or not secrets.compare_digest(provided, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
