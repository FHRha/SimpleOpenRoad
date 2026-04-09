"""Repository for minute-bucket usage counters."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.types import LLMUsage
from app.storage.db import SQLiteDB


class StatsRepository:
    def __init__(self, db: SQLiteDB):
        self.db = db

    def record_request(
        self,
        provider: str,
        key_id: str,
        success: bool,
        latency_ms: float,
        usage: LLMUsage | None = None,
    ) -> None:
        now = datetime.now(UTC)
        bucket = now.replace(second=0, microsecond=0).isoformat()
        usage_obj = usage or LLMUsage()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO usage_stats(
                  bucket_minute, provider, key_id,
                  requests_total, success_total, failure_total,
                  tokens_prompt, tokens_completion, estimated_cost_usd, avg_latency_ms
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(bucket_minute, provider, key_id) DO UPDATE SET
                  requests_total = requests_total + 1,
                  success_total = success_total + excluded.success_total,
                  failure_total = failure_total + excluded.failure_total,
                  tokens_prompt = tokens_prompt + excluded.tokens_prompt,
                  tokens_completion = tokens_completion + excluded.tokens_completion,
                  avg_latency_ms = ((avg_latency_ms * requests_total) + excluded.avg_latency_ms) / (requests_total + 1)
                """,
                (
                    bucket,
                    provider,
                    key_id,
                    1 if success else 0,
                    0 if success else 1,
                    usage_obj.prompt_tokens,
                    usage_obj.completion_tokens,
                    latency_ms,
                ),
            )

    def summary(self) -> dict:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT
                  COALESCE(SUM(requests_total), 0) AS requests_total,
                  COALESCE(SUM(success_total), 0) AS success_total,
                  COALESCE(SUM(failure_total), 0) AS failure_total,
                  COALESCE(AVG(avg_latency_ms), 0) AS avg_latency_ms,
                  COALESCE(SUM(tokens_prompt), 0) AS tokens_prompt,
                  COALESCE(SUM(tokens_completion), 0) AS tokens_completion
                FROM usage_stats
                """
            ).fetchone()
            return dict(row) if row else {}
