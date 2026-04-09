"""Repository for per-attempt routing execution traces."""

from __future__ import annotations

from app.storage.db import SQLiteDB


class AttemptsRepository:
    def __init__(self, db: SQLiteDB):
        self.db = db

    def add_attempt(
        self,
        request_id: str,
        route_alias: str | None,
        provider: str,
        key_id: str,
        model: str,
        attempt_index: int,
        outcome: str,
        error_class: str | None,
        latency_ms: float,
        created_at: str,
    ) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO request_attempts(
                  request_id, route_alias, provider, key_id, model,
                  attempt_index, outcome, error_class, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    route_alias,
                    provider,
                    key_id,
                    model,
                    attempt_index,
                    outcome,
                    error_class,
                    latency_ms,
                    created_at,
                ),
            )

    def list_for_request(self, request_id: str) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM request_attempts WHERE request_id = ? ORDER BY attempt_index",
                (request_id,),
            ).fetchall()
            return [dict(r) for r in rows]
