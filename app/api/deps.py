"""FastAPI dependencies for container access and auth checks."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.container import AppContainer
from app.core.security import extract_admin_key, extract_user_api_key


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="Application container is not initialized")
    return container


def require_user_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> None:
    cfg = container.runtime_config.get()
    if not cfg.security.require_master_key:
        return
    provided = extract_user_api_key(dict(request.headers))
    expected = container.runtime_config.env.master_api_key
    if not expected:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="MASTER_API_KEY is not configured")
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def require_admin_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> None:
    cfg = container.runtime_config.get()
    if not cfg.security.require_admin_key:
        return
    provided = extract_admin_key(dict(request.headers))
    expected = container.runtime_config.env.admin_api_key
    if not expected:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ADMIN_API_KEY is not configured")
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
