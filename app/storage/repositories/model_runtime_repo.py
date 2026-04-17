"""Runtime state for provider/model quarantine decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.errors import ErrorClass
from app.core.utils import utcnow_iso
from app.storage.db import SQLiteDB


class ModelRuntimeRepository:
    def __init__(self, db: SQLiteDB):
        self.db = db

    def list_active_quarantines(self) -> dict[tuple[str, str], dict]:
        now = datetime.now(UTC).isoformat()
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM model_runtime_state
                WHERE quarantined_until IS NOT NULL
                  AND quarantined_until > ?
                ORDER BY provider, model
                """,
                (now,),
            ).fetchall()
        return {(str(row["provider"]), str(row["model"])): dict(row) for row in rows}

    def get_state(self, provider: str, model: str) -> dict | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM model_runtime_state WHERE provider = ? AND model = ?",
                (provider, model),
            ).fetchone()
        return dict(row) if row else None

    def record_success(self, provider: str, model: str, latency_ms: float) -> None:
        now = utcnow_iso()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO model_runtime_state (
                  provider, model, consecutive_failures, quarantined_until,
                  last_success_at, success_count, failure_count, avg_latency_ms
                ) VALUES (?, ?, 0, NULL, ?, 1, 0, ?)
                ON CONFLICT(provider, model) DO UPDATE SET
                  consecutive_failures = 0,
                  quarantined_until = NULL,
                  last_error_class = NULL,
                  last_error_message = NULL,
                  last_success_at = excluded.last_success_at,
                  success_count = success_count + 1,
                  avg_latency_ms = CASE
                    WHEN avg_latency_ms = 0 THEN excluded.avg_latency_ms
                    ELSE ((avg_latency_ms * 0.8) + (excluded.avg_latency_ms * 0.2))
                  END
                """,
                (provider, model, now, latency_ms),
            )

    def record_failure(
        self,
        *,
        provider: str,
        model: str,
        error_class: ErrorClass,
        error_message: str,
        failure_threshold: int,
        ttl_seconds: int,
    ) -> dict:
        now = utcnow_iso()
        existing = self.get_state(provider, model)
        next_failures = int((existing or {}).get("consecutive_failures", 0) or 0) + 1
        quarantined_until = None
        if next_failures >= max(1, failure_threshold) and ttl_seconds > 0:
            quarantined_until = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO model_runtime_state (
                  provider, model, consecutive_failures, quarantined_until,
                  last_error_at, last_error_class, last_error_message,
                  success_count, failure_count, avg_latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, 0)
                ON CONFLICT(provider, model) DO UPDATE SET
                  consecutive_failures = excluded.consecutive_failures,
                  quarantined_until = excluded.quarantined_until,
                  last_error_at = excluded.last_error_at,
                  last_error_class = excluded.last_error_class,
                  last_error_message = excluded.last_error_message,
                  failure_count = failure_count + 1
                """,
                (
                    provider,
                    model,
                    next_failures,
                    quarantined_until,
                    now,
                    error_class.value,
                    error_message[:1000],
                ),
            )
        return {
            "provider": provider,
            "model": model,
            "consecutive_failures": next_failures,
            "quarantined_until": quarantined_until,
            "last_error_class": error_class.value,
        }

    def reset(self, provider: str | None = None, model: str | None = None) -> int:
        clauses: list[str] = []
        args: list[str] = []
        if provider:
            clauses.append("provider = ?")
            args.append(provider)
        if model:
            clauses.append("model = ?")
            args.append(model)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE model_runtime_state
                SET consecutive_failures = 0,
                    quarantined_until = NULL,
                    last_error_class = NULL,
                    last_error_message = NULL
                {where}
                """,
                tuple(args),
            )
            return int(cursor.rowcount or 0)
