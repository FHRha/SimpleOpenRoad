"""Small wrapper around storage-level stats aggregation."""

from __future__ import annotations

from app.storage.repositories.stats_repo import StatsRepository


class MetricsService:
    def __init__(self, stats_repo: StatsRepository):
        self.stats_repo = stats_repo

    def get_summary(self) -> dict:
        return self.stats_repo.summary()
