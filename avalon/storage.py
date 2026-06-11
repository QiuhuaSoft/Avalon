from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .models import Event


class EventStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._memory_conn: sqlite3.Connection | None = None
        if path == ":memory:":
            # Each sqlite3.connect(":memory:") opens a brand-new empty database,
            # so the schema would vanish between calls; keep one connection alive.
            self._memory_conn = sqlite3.connect(":memory:")
        else:
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return self._memory_conn if self._memory_conn is not None else sqlite3.connect(self.path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def append(self, event: Event) -> None:
        payload_json = json.dumps(event.payload)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events (ts, type, payload) VALUES (?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), event.type, payload_json),
            )
            conn.commit()

    def list_events(self) -> List[Event]:
        with self._connect() as conn:
            rows = conn.execute("SELECT type, payload FROM events ORDER BY id ASC").fetchall()
        events: List[Event] = []
        for row in rows:
            events.append(Event(type=row[0], payload=json.loads(row[1])))
        return events

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM events")
            conn.commit()
