"""Admin API routes for operations and diagnostics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container, require_admin_auth
from app.api.schemas_admin import ReloadConfigRequestSchema, ValidateKeyRequestSchema
from app.container import AppContainer
from app.core.errors import ConfigError

router = APIRouter()


@router.get("/keys", dependencies=[Depends(require_admin_auth)])
async def keys(container: AppContainer = Depends(get_container)) -> list[dict]:
    return container.admin_service.list_keys()


@router.post("/admin/validate-key", dependencies=[Depends(require_admin_auth)])
async def validate_key(
    payload: ValidateKeyRequestSchema,
    container: AppContainer = Depends(get_container),
) -> dict:
    return await container.admin_service.validate_key(provider=payload.provider, key_id=payload.key_id)


@router.post("/admin/reload-config", dependencies=[Depends(require_admin_auth)])
async def reload_config(
    payload: ReloadConfigRequestSchema,
    container: AppContainer = Depends(get_container),
) -> dict:
    try:
        if payload.config_path:
            container.runtime_config.reload(payload.config_path)
            container.key_registry.sync_defaults(container.runtime_config.get())
            container.routing_engine.refresh_providers()
            container.health_checker.providers = container.routing_engine.providers
            container.inventory_discovery.refresh_providers(container.routing_engine.providers)
            snapshot = await container.admin_service.refresh_inventory()
            return {"status": "ok", "generated_aliases": len(snapshot.get("generated_aliases", []))}
        result = container.admin_service.reload_config()
        snapshot = await container.admin_service.refresh_inventory()
        result["generated_aliases"] = len(snapshot.get("generated_aliases", []))
        return result
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin/stats", dependencies=[Depends(require_admin_auth)])
async def stats(container: AppContainer = Depends(get_container)) -> dict:
    return container.admin_service.stats()


@router.get("/admin/health", dependencies=[Depends(require_admin_auth)])
async def health_status(container: AppContainer = Depends(get_container)) -> list[dict]:
    return container.admin_service.latest_health()
