"""Backup script. `pg_dump` itself is mocked — no live server needed."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts import backup


# ── URL parsing ────────────────────────────────────────────────────────────────

def test_url_becomes_libpq_env_and_dbname():
    env, name = backup.pg_env_and_target(
        "postgresql+psycopg://alice:s3cret@dbhost:6543/mydb")
    assert name == "mydb"
    assert env["PGHOST"] == "dbhost"
    assert env["PGPORT"] == "6543"
    assert env["PGUSER"] == "alice"
    assert env["PGPASSWORD"] == "s3cret"


def test_password_is_url_decoded():
    env, _ = backup.pg_env_and_target(
        "postgresql+psycopg://u:p%40ss%2Fword@h:5432/d")
    assert env["PGPASSWORD"] == "p@ss/word"


def test_missing_dbname_falls_back():
    _, name = backup.pg_env_and_target("postgresql+psycopg://u:p@h:5432/")
    assert name == "betterread"


# ── rotation ───────────────────────────────────────────────────────────────────

def _touch(d: Path, stamps):
    for s in stamps:
        (d / f"{backup.PREFIX}{s}{backup.SUFFIX}").write_text("x")


def test_rotation_keeps_the_newest_n(tmp_path):
    _touch(tmp_path, ["20260101T000000Z", "20260102T000000Z",
                      "20260103T000000Z", "20260104T000000Z"])
    removed = backup.rotate(tmp_path, keep=2)
    left = sorted(p.name for p in tmp_path.glob("*.dump"))
    assert len(removed) == 2
    assert left == [f"{backup.PREFIX}20260103T000000Z{backup.SUFFIX}",
                    f"{backup.PREFIX}20260104T000000Z{backup.SUFFIX}"]


def test_rotation_leaves_foreign_files_alone(tmp_path):
    """Including the legacy SQLite backups, which may still be sitting there."""
    _touch(tmp_path, ["20260101T000000Z", "20260102T000000Z"])
    (tmp_path / "important.txt").write_text("keep me")
    (tmp_path / "rss-old.db").write_text("legacy sqlite backup")
    backup.rotate(tmp_path, keep=1)
    assert (tmp_path / "important.txt").exists()
    assert (tmp_path / "rss-old.db").exists()


def test_rotation_disabled_when_keep_is_zero(tmp_path):
    _touch(tmp_path, ["20260101T000000Z", "20260102T000000Z"])
    assert backup.rotate(tmp_path, keep=0) == []
    assert len(list(tmp_path.glob("*.dump"))) == 2


# ── main ───────────────────────────────────────────────────────────────────────

@patch("scripts.backup.subprocess.run")
def test_main_invokes_pg_dump_in_custom_format(mock_run, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/mydb")
    assert backup.main([]) == 0
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "pg_dump"
    assert "--format=custom" in cmd
    assert cmd[-1] == "mydb"
    assert backup.PREFIX in capsys.readouterr().out


@patch("scripts.backup.subprocess.run")
def test_main_never_puts_the_password_on_the_command_line(mock_run, tmp_path, monkeypatch):
    """It would be visible in `ps` to anyone on the box."""
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:hunter2@h:5432/d")
    backup.main([])
    assert "hunter2" not in " ".join(mock_run.call_args[0][0])
    assert mock_run.call_args.kwargs["env"]["PGPASSWORD"] == "hunter2"


@patch("scripts.backup.subprocess.run", side_effect=FileNotFoundError)
def test_main_reports_missing_pg_dump(_mock, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    assert backup.main([]) == 2
    assert "pg_dump not found" in capsys.readouterr().err


@patch("scripts.backup.subprocess.run")
def test_failed_dump_leaves_no_truncated_file(mock_run, tmp_path, monkeypatch, capsys):
    """A partial file would look like a usable backup until you needed it."""
    def _fail(cmd, **kw):
        Path(cmd[cmd.index("--file") + 1]).write_text("half a dump")
        raise subprocess.CalledProcessError(1, cmd, stderr=b"connection refused")
    mock_run.side_effect = _fail
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    assert backup.main([]) == 1
    assert list(tmp_path.glob("*.dump")) == []
    assert "connection refused" in capsys.readouterr().err


@patch("scripts.backup.subprocess.run")
def test_main_rotates_after_writing(mock_run, tmp_path, monkeypatch):
    _touch(tmp_path, ["20200101T000000Z", "20200102T000000Z"])
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("KEEP", "1")
    backup.main([])
    assert len(list(tmp_path.glob("*.dump"))) == 1


@patch("scripts.backup.subprocess.run")
def test_main_tolerates_invalid_keep(mock_run, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("KEEP", "not-a-number")
    assert backup.main([]) == 0


@patch("scripts.backup.subprocess.run")
def test_main_creates_the_backup_directory(mock_run, tmp_path, monkeypatch):
    target = tmp_path / "nested" / "backups"
    monkeypatch.setenv("BACKUP_DIR", str(target))
    assert backup.main([]) == 0
    assert target.is_dir()
