from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.checkpoint_db import checkpoint_database


def test_checkpoint_database_includes_uncheckpointed_wal_rows(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite"
    destination = tmp_path / "checkpoint.sqlite"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE events(value TEXT NOT NULL)")
    connection.execute("INSERT INTO events VALUES ('latest')")
    connection.commit()
    try:
        digest = checkpoint_database(source, destination)
    finally:
        connection.close()
    restored = sqlite3.connect(destination)
    try:
        assert restored.execute("SELECT value FROM events").fetchone() == ("latest",)
    finally:
        restored.close()
    assert len(digest) == 64
    with pytest.raises(FileExistsError):
        checkpoint_database(source, destination)
