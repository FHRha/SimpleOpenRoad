"""In-memory and file-backed cache for runtime inventory snapshots."""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import RLock

from app.inventory.models import InventorySnapshot


class InventoryCache:
    def __init__(self, file_path: Path | None = None) -> None:
        self._lock = RLock()
        self._snapshot: InventorySnapshot | None = None
        self._cached_at: float | None = None
        self.file_path = file_path

    def get(self, stale_after: float | None = None) -> InventorySnapshot | None:
        with self._lock:
            if self._snapshot is not None and _is_stale(self._cached_at, stale_after):
                self._snapshot = None
                self._cached_at = None
            return self._snapshot

    def set(self, snapshot: InventorySnapshot, cached_at: float | None = None) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._cached_at = cached_at or time.time()

    def load_file(self, fingerprint: str, stale_after: float | None = None) -> InventorySnapshot | None:
        if self.file_path is None or not self.file_path.exists():
            return None
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("fingerprint") != fingerprint:
            return None
        cached_at = float(payload.get("cached_at", 0) or 0)
        if cached_at <= 0 or _is_stale(cached_at, stale_after):
            return None
        snapshot_payload = payload.get("snapshot")
        if not isinstance(snapshot_payload, dict):
            return None
        try:
            snapshot = InventorySnapshot.from_dict(snapshot_payload)
        except TypeError:
            return None
        self.set(snapshot, cached_at=cached_at)
        return snapshot

    def save_file(self, snapshot: InventorySnapshot, fingerprint: str) -> None:
        if self.file_path is None:
            return
        payload = {
            "cached_at": time.time(),
            "fingerprint": fingerprint,
            "snapshot": snapshot.to_dict(),
        }
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        except OSError:
            return

    def clear(self) -> None:
        with self._lock:
            self._snapshot = None
            self._cached_at = None
        if self.file_path is None:
            return
        try:
            self.file_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _is_stale(cached_at: float | None, stale_after: float | None) -> bool:
    return stale_after is not None and (cached_at is None or cached_at < stale_after)
