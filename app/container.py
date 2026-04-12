"""Application container wiring config, storage, services and runtime components."""

from __future__ import annotations

from importlib.resources import files
from app.config.runtime import RuntimeConfig
from app.health.checker import HealthChecker
from app.health.scheduler import HealthScheduler
from app.observability.metrics import MetricsService
from app.registry.keys import KeyRegistry
from app.router.engine import RoutingEngine
from app.services.admin_service import AdminService
from app.services.gateway_service import GatewayService
from app.storage.db import SQLiteDB
from app.storage.repositories.attempts_repo import AttemptsRepository
from app.storage.repositories.health_repo import HealthRepository
from app.storage.repositories.keys_repo import KeysRuntimeRepository
from app.storage.repositories.stats_repo import StatsRepository


class AppContainer:
    def __init__(self, config_path: str | None = None):
        self.runtime_config = RuntimeConfig.bootstrap(config_path=config_path)

        db_path = self.runtime_config.get().storage.sqlite_path
        self.db = SQLiteDB(db_path)
        schema_path = files("app.storage").joinpath("schema.sql")
        self.db.initialize(str(schema_path))

        self.keys_repo = KeysRuntimeRepository(self.db)
        self.health_repo = HealthRepository(self.db)
        self.attempts_repo = AttemptsRepository(self.db)
        self.stats_repo = StatsRepository(self.db)

        self.key_registry = KeyRegistry(self.keys_repo)
        self.key_registry.sync_defaults(self.runtime_config.get())

        self.routing_engine = RoutingEngine(
            runtime_config=self.runtime_config,
            key_registry=self.key_registry,
            attempts_repo=self.attempts_repo,
            stats_repo=self.stats_repo,
        )

        self.health_checker = HealthChecker(
            runtime_config=self.runtime_config,
            providers=self.routing_engine.providers,
            key_registry=self.key_registry,
            health_repo=self.health_repo,
        )
        self.health_scheduler = HealthScheduler(
            checker=self.health_checker,
            interval_seconds=self.runtime_config.get().health.check_interval_seconds,
        )

        self.metrics_service = MetricsService(self.stats_repo)
        self.gateway_service = GatewayService(self.routing_engine)
        self.admin_service = AdminService(
            runtime_config=self.runtime_config,
            key_registry=self.key_registry,
            health_checker=self.health_checker,
            health_repo=self.health_repo,
            metrics=self.metrics_service,
            routing_engine=self.routing_engine,
        )
