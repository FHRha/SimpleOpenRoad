"""Repository for mutable runtime state of configured API keys."""

from __future__ import annotations

from datetime import UTC, datetime

from app.storage.db import SQLiteDB


class KeysRuntimeRepository:
    def __init__(self, db: SQLiteDB):
        self.db = db

    def list_states(self) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM key_runtime_state ORDER BY provider, key_id").fetchall()
            return [dict(r) for r in rows]

    def get_state(self, key_id: str) -> dict | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM key_runtime_state WHERE key_id = ?",
                (key_id,),
            ).fetchone()
            return dict(row) if row else None

    def upsert_default(self, provider: str, key_id: str, active: bool) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO key_runtime_state (key_id, provider, active)
                VALUES (?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                  provider = excluded.provider,
                  active = excluded.active
                """,
                (key_id, provider, 1 if active else 0),
            )

    def set_active(self, key_id: str, active: bool) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE key_runtime_state SET active = ? WHERE key_id = ?",
                (1 if active else 0, key_id),
            )

    def record_success(self, key_id: str, latency_ms: float) -> None:
        now = datetime.now(UTC).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE key_runtime_state
                SET status = 'valid',
                    consecutive_errors = 0,
                    cooldown_until = NULL,
                    last_success_at = ?,
                    success_count = success_count + 1,
                    avg_latency_ms = CASE
                      WHEN success_count = 0 THEN ?
                      ELSE ((avg_latency_ms * success_count) + ?) / (success_count + 1)
                    END
                WHERE key_id = ?
                """,
                (now, latency_ms, latency_ms, key_id),
            )

    def record_failure(
        self,
        key_id: str,
        error_code: str,
        error_message: str,
        cooldown_until_iso: str | None,
        new_status: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE key_runtime_state
                SET status = COALESCE(?, status),
                    consecutive_errors = consecutive_errors + 1,
                    last_error_at = ?,
                    last_error_code = ?,
                    last_error_message = ?,
                    cooldown_until = COALESCE(?, cooldown_until),
                    failure_count = failure_count + 1
                WHERE key_id = ?
                """,
                (new_status, now, error_code, error_message[:1000], cooldown_until_iso, key_id),
            )

    def bump_switch_counter(self, key_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE key_runtime_state SET switch_count = switch_count + 1 WHERE key_id = ?",
                (key_id,),
            )

    def set_status(self, key_id: str, status: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE key_runtime_state SET status = ? WHERE key_id = ?",
                (status, key_id),
            )

    def reset_state(self, provider: str, key_id: str, active: bool) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO key_runtime_state (key_id, provider, active)
                VALUES (?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                  provider = excluded.provider,
                  active = excluded.active,
                  status = 'unknown',
                  consecutive_errors = 0,
                  cooldown_until = NULL,
                  last_check_at = NULL,
                  last_success_at = NULL,
                  last_error_at = NULL,
                  last_error_code = NULL,
                  last_error_message = NULL,
                  success_count = 0,
                  failure_count = 0,
                  switch_count = 0,
                  avg_latency_ms = 0
                """,
                (key_id, provider, 1 if active else 0),
            )

    def update_health(
        self,
        key_id: str,
        status: str,
        checked_at: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        with self.db.connection() as conn:
            if status == "valid":
                conn.execute(
                    """
                    UPDATE key_runtime_state
                    SET status = ?,
                        last_check_at = ?,
                        consecutive_errors = 0,
                        cooldown_until = NULL,
                        last_error_code = NULL,
                        last_error_message = NULL
                    WHERE key_id = ?
                    """,
                    (status, checked_at, key_id),
                )
                return
            conn.execute(
                """
                UPDATE key_runtime_state
                SET status = ?,
                    last_check_at = ?,
                    last_error_code = ?,
                    last_error_message = ?
                WHERE key_id = ?
                """,
                (status, checked_at, error_code, error_message, key_id),
            )
