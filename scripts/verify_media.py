#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from videoforge.assembly import probe_media, verify_video


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect VideoForge MP4 outputs with ffprobe")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--final", action="store_true", help="probe final cuts without 5s checks")
    args = parser.parse_args()
    results = {
        str(path): probe_media(path) if args.final else verify_video(path)
        for path in args.files
    }
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

