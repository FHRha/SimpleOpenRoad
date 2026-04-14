"""Repository for remembered successful route models."""

from __future__ import annotations

from app.storage.db import SQLiteDB


class RouteModelMemoryRepository:
    def __init__(self, db: SQLiteDB):
        self.db = db

    def get(self, route_alias: str, profile: str, context_bucket: str) -> dict | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM route_model_memory
                WHERE route_alias = ? AND profile = ? AND context_bucket = ?
                """,
                (route_alias, profile, context_bucket),
            ).fetchone()
            return dict(row) if row else None

    def record_success(
        self,
        *,
        route_alias: str,
        profile: str,
        context_bucket: str,
        provider: str,
        model: str,
        latency_ms: float,
        updated_at: str,
    ) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO route_model_memory(
                  route_alias, profile, context_bucket, provider, model,
                  success_count, avg_latency_ms, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(route_alias, profile, context_bucket) DO UPDATE SET
                  provider = excluded.provider,
                  model = excluded.model,
                  success_count = route_model_memory.success_count + 1,
                  avg_latency_ms = ((route_model_memory.avg_latency_ms * route_model_memory.success_count)
                    + excluded.avg_latency_ms) / (route_model_memory.success_count + 1),
                  updated_at = excluded.updated_at
                """,
                (route_alias, profile, context_bucket, provider, model, latency_ms, updated_at),
            )
