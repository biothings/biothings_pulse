"""SQLite-backed state store for local development."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from .base import SourceState, StateStore, deserialize_state


class SQLiteStateStore(StateStore):
    """Single-file store. Thread-safe via a lock (checks run in a threadpool)."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_state (
                    repo   TEXT NOT NULL,
                    plugin TEXT NOT NULL,
                    doc    TEXT NOT NULL,
                    PRIMARY KEY (repo, plugin)
                )
                """
            )
            self._conn.commit()

    def get(self, repo: str, plugin: str) -> Optional[SourceState]:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc FROM source_state WHERE repo = ? AND plugin = ?",
                (repo, plugin),
            ).fetchone()
        if row is None:
            return None
        return deserialize_state(row["doc"])

    def put(self, state: SourceState) -> None:
        doc = state.model_dump_json()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO source_state (repo, plugin, doc) VALUES (?, ?, ?)
                ON CONFLICT(repo, plugin) DO UPDATE SET doc = excluded.doc
                """,
                (state.repo, state.plugin, doc),
            )
            self._conn.commit()

    def list_all(self) -> List[SourceState]:
        with self._lock:
            rows = self._conn.execute("SELECT doc FROM source_state").fetchall()
        states = [deserialize_state(r["doc"]) for r in rows]
        return [s for s in states if s is not None]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
