from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path


def checkpoint_database(source: Path, destination: Path) -> str:
    """Create a transactionally complete SQLite backup, including WAL changes."""
    if destination.exists():
        raise FileExistsError(f"checkpoint already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError(f"checkpoint integrity failed: {integrity}")
    finally:
        destination_connection.close()
        source_connection.close()
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an immutable, WAL-safe VideoForge database checkpoint."
    )
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=Path("data/videoforge.db"))
    args = parser.parse_args()
    digest = checkpoint_database(args.source, args.destination)
    print(f"checkpoint={args.destination}")
    print(f"sha256={digest}")


if __name__ == "__main__":
    main()
