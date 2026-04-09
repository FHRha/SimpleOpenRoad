"""Repository for key health-check history."""

from __future__ import annotations

import json

from app.storage.db import SQLiteDB


class HealthRepository:
    def __init__(self, db: SQLiteDB):
        self.db = db

    def add_result(
        self,
        key_id: str,
        provider: str,
        status: str,
        latency_ms: float | None,
        models: list[str],
        error_code: str | None,
        error_message: str | None,
        checked_at: str,
    ) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO health_checks(
                  key_id, provider, status, latency_ms, models_json,
                  error_code, error_message, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key_id,
                    provider,
                    status,
                    latency_ms,
                    json.dumps(models),
                    error_code,
                    (error_message or "")[:1000],
                    checked_at,
                ),
            )

    def latest_by_key(self) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT h.*
                FROM health_checks h
                JOIN (
                  SELECT key_id, MAX(checked_at) AS max_checked
                  FROM health_checks
                  GROUP BY key_id
                ) x
                ON h.key_id = x.key_id AND h.checked_at = x.max_checked
                ORDER BY h.provider, h.key_id
                """
            ).fetchall()
            return [dict(r) for r in rows]
