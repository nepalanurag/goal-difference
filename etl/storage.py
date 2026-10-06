"""Storage: Parquet lake plus the SQLite ops ledger (Phase 9.0).

The lake lives under data/lake/ (raw fixtures, built features) as Parquet
files, written alongside the existing CSVs so the cutover stays reversible.
Parquet I/O goes through DuckDB (no pyarrow needed): DuckDB also queries the
files in place.

data/ops.sqlite is the operational ledger: schema migrations, ingest-run
audit rows, and the model registry. Schema changes are additive only and
tracked in schema_migrations.

Usage:
    python -m etl.storage   # init the ops db (idempotent)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .config import settings
from .logging_setup import get_logger

log = get_logger(__name__)

OPS_DB_NAME = "ops.sqlite"

# Additive migrations only: each entry is (version, ddl). Applied once each,
# recorded in schema_migrations.
MIGRATIONS: list[tuple[str, str]] = [
    ("9.0.1", """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ingest_runs (
            run_id     TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status     TEXT NOT NULL,
            rows_in    INTEGER,
            rows_out   INTEGER,
            notes      TEXT
        );
        CREATE TABLE IF NOT EXISTS model_registry (
            model_version      TEXT PRIMARY KEY,
            league             TEXT NOT NULL,
            git_sha            TEXT,
            feature_set_version TEXT,
            data_hash          TEXT,
            created_at         TEXT NOT NULL,
            stage              TEXT NOT NULL DEFAULT 'staging'
        );
    """),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ops_db_path() -> Path:
    return settings.data_dir / OPS_DB_NAME


def lake_dir() -> Path:
    """Root of the Parquet lake: data/lake."""
    return settings.data_dir / "lake"


def raw_lake_path(league: str) -> Path:
    return lake_dir() / "raw" / league / "fixtures.parquet"


def features_lake_path(league: str) -> Path:
    return lake_dir() / "features" / league / "features.parquet"


def write_parquet(df: pd.DataFrame, path: str | Path) -> Path:
    """Write a frame to Parquet via DuckDB. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    duckdb.from_df(df).write_parquet(str(path))
    log.info("parquet_written", rows=len(df), path=str(path))
    return path


def read_parquet(path: str | Path) -> pd.DataFrame:
    """Read a Parquet file back into a frame via DuckDB."""
    return duckdb.read_parquet(str(path)).df()


def init_ops_db(path: str | Path | None = None) -> Path:
    """Create data/ops.sqlite and apply any pending migrations (idempotent)."""
    path = Path(path) if path else ops_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {row[0] for row in con.execute("SELECT version FROM schema_migrations")}
        for version, ddl in MIGRATIONS:
            if version in applied:
                continue
            con.executescript(ddl)
            con.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, _now()),
            )
            log.info("migration_applied", version=version)
        con.commit()
    finally:
        con.close()
    return path


def start_ingest_run(notes: str = "", path: str | Path | None = None) -> str:
    """Record the start of an ingest run. Returns the run id."""
    run_id = f"refresh-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    con = sqlite3.connect(Path(path) if path else ops_db_path())
    try:
        con.execute(
            "INSERT INTO ingest_runs (run_id, started_at, status, notes)"
            " VALUES (?, ?, 'started', ?)",
            (run_id, _now(), notes),
        )
        con.commit()
    finally:
        con.close()
    log.info("ingest_run_started", run_id=run_id)
    return run_id


def finish_ingest_run(run_id: str, status: str, rows_in: int | None = None,
                      rows_out: int | None = None, notes: str = "",
                      path: str | Path | None = None) -> None:
    """Mark an ingest run finished (or failed)."""
    con = sqlite3.connect(Path(path) if path else ops_db_path())
    try:
        con.execute(
            "UPDATE ingest_runs SET finished_at = ?, status = ?,"
            " rows_in = COALESCE(?, rows_in), rows_out = ?, notes = ?"
            " WHERE run_id = ?",
            (_now(), status, rows_in, rows_out, notes, run_id),
        )
        con.commit()
    finally:
        con.close()
    log.info("ingest_run_finished", run_id=run_id, status=status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Init the ops ledger database.")
    parser.parse_args(argv)
    path = init_ops_db()
    log.info("ops_db_ready", path=str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
