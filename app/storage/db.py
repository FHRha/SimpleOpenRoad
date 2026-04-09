"""SQLite connection and schema bootstrap helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SQLiteDB:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self, schema_path: str) -> None:
        schema = Path(schema_path).read_text(encoding="utf-8")
        with self.connection() as conn:
            conn.executescript(schema)
