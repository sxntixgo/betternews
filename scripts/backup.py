#!/usr/bin/env python3
"""Timestamped Postgres backups with rotation.

Env vars:
  DATABASE_URL  source database (default: the app's)
  BACKUP_DIR    destination directory (default ./data/backups)
  KEEP          how many dumps to retain, oldest deleted beyond this (default 7)

Uses `pg_dump -Fc` — compressed, and restorable selectively with `pg_restore`.
Replaces the SQLite `.backup` API this used before the Postgres migration.

Exit code 0 on success. Recommended cron entry:
    0 4 * * * /usr/bin/python3 /app/scripts/backup.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import database_url  # noqa: E402

PREFIX = "betterread-"
SUFFIX = ".dump"


def pg_env_and_target(url: str) -> tuple[dict, str]:
    """Split a SQLAlchemy URL into libpq env vars plus the database name.

    The password goes in the environment, never on the command line where it
    would show up in `ps`.
    """
    parsed = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
    env = os.environ.copy()
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return env, (parsed.path or "/").lstrip("/") or "betterread"


def rotate(backup_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` dumps. Only ever touches our own files."""
    dumps = sorted(
        (p for p in backup_dir.glob(f"{PREFIX}*{SUFFIX}") if p.is_file()),
        key=lambda p: p.name,
    )
    removed = []
    for old in dumps[:-keep] if keep > 0 else []:
        old.unlink()
        removed.append(old)
    return removed


def main(argv: list[str] | None = None) -> int:
    env, dbname = pg_env_and_target(database_url())

    backup_dir = Path(os.environ.get("BACKUP_DIR", "./data/backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        keep = int(os.environ.get("KEEP", "7"))
    except ValueError:
        keep = 7

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{PREFIX}{stamp}{SUFFIX}"

    try:
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl",
             "--file", str(target), dbname],
            env=env, check=True, capture_output=True,
        )
    except FileNotFoundError:
        print("ERROR: pg_dump not found on PATH", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        # Never leave a truncated file lying around looking like a usable backup.
        target.unlink(missing_ok=True)
        detail = (exc.stderr or b"").decode(errors="replace").strip()
        print(f"ERROR: pg_dump failed: {detail}", file=sys.stderr)
        return 1

    print(target)
    for old in rotate(backup_dir, keep):
        print(f"removed {old}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
