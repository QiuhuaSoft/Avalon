"""EventStore tests: in-memory persistence, directory creation, timestamps."""

import sqlite3
from datetime import datetime

from avalon.models import Event
from avalon.storage import EventStore


def test_memory_store_persists_between_operations():
    store = EventStore(":memory:")
    store.append(Event(type="alpha", payload={"n": 1}))
    store.append(Event(type="beta", payload={"n": 2}))
    events = store.list_events()
    assert [e.type for e in events] == ["alpha", "beta"]
    store.clear()
    assert store.list_events() == []
    # The schema must survive a clear too.
    store.append(Event(type="gamma", payload={}))
    assert [e.type for e in store.list_events()] == ["gamma"]


def test_file_store_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "deeply" / "nested" / "events.sqlite"
    store = EventStore(str(path))
    store.append(Event(type="created", payload={"ok": True}))
    assert path.exists()
    assert [e.type for e in store.list_events()] == ["created"]


def test_payload_roundtrips_through_sqlite(tmp_path):
    path = tmp_path / "events.sqlite"
    store = EventStore(str(path))
    payload = {"team": ["p1", "p2"], "approvals": 3, "nested": {"deep": [1, 2]}}
    store.append(Event(type="team_proposed", payload=payload))
    assert store.list_events()[0].payload == payload


def test_timestamps_are_timezone_aware_utc(tmp_path):
    path = tmp_path / "events.sqlite"
    store = EventStore(str(path))
    store.append(Event(type="tick", payload={}))
    with sqlite3.connect(str(path)) as conn:
        (ts,) = conn.execute("SELECT ts FROM events").fetchone()
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
