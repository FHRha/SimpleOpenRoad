"""FastAPI entrypoint for the AI gateway router."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.middleware import RequestContextMiddleware
from app.api.routes_admin import router as admin_router
from app.api.routes_public import router as public_router
from app.container import AppContainer
from app.observability.logging import setup_logging


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    container: AppContainer = app.state.container
    cfg = container.runtime_config.get()
    await container.admin_service.refresh_inventory()
    if cfg.health.startup_check:
        await container.admin_service.validate_all_keys()
    container.health_scheduler.interval_seconds = cfg.health.check_interval_seconds
    container.health_scheduler.start()
    container.inventory_scheduler.start()
    try:
        yield
    finally:
        await container.inventory_scheduler.stop()
        await container.health_scheduler.stop()


def create_app() -> FastAPI:
    config_path = os.getenv("APP_CONFIG_PATH")
    container = AppContainer(config_path=config_path)

    setup_logging(
        level=container.runtime_config.env.app_log_level,
        json_logs=container.runtime_config.get().observability.json_logs,
    )

    app = FastAPI(title="SimpleOpenRoad AI Gateway", version="0.3.0", lifespan=app_lifespan)
    app.state.container = container
    app.add_middleware(RequestContextMiddleware)

    app.include_router(public_router)
    app.include_router(admin_router)

    return app


app = create_app()
