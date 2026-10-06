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
import json
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
    ("9.3.1", """
        CREATE TABLE IF NOT EXISTS runs (
            run_id              TEXT PRIMARY KEY,
            git_sha             TEXT,
            started_at          TEXT NOT NULL,
            finished_at         TEXT,
            league              TEXT NOT NULL,
            params_json         TEXT,
            seed                INTEGER,
            data_hash           TEXT,
            feature_set_version TEXT,
            status              TEXT NOT NULL DEFAULT 'started'
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            eval_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         TEXT,
            model_version  TEXT,
            league         TEXT NOT NULL,
            protocol       TEXT NOT NULL,
            window_start   TEXT,
            window_end     TEXT,
            metric_name    TEXT NOT NULL,
            metric_value   REAL,
            evaluated_at   TEXT NOT NULL
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


def features_lake_versioned_path(league: str, version: str) -> Path:
    """Versioned feature snapshot: features_v{version}.parquet.

    Version is the first 8 chars of feature_logic_version(), so a feature
    set is always addressable by the exact code that built it."""
    return lake_dir() / "features" / league / f"features_v{version}.parquet"


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


def start_run(league: str, params: dict, seed: int | None,
              data_hash: str | None, feature_set_version: str | None,
              git_sha: str | None = None,
              path: str | Path | None = None) -> str:
    """Record the start of a training run. Returns the run id."""
    run_id = f"fit-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    con = sqlite3.connect(Path(path) if path else ops_db_path())
    try:
        con.execute(
            "INSERT INTO runs (run_id, git_sha, started_at, league,"
            " params_json, seed, data_hash, feature_set_version, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'started')",
            (run_id, git_sha, _now(), league, json.dumps(params), seed,
             data_hash, feature_set_version),
        )
        con.commit()
    finally:
        con.close()
    log.info("run_started", run_id=run_id, league=league)
    return run_id


def finish_run(run_id: str, status: str,
               path: str | Path | None = None) -> None:
    """Mark a training run finished (or failed)."""
    con = sqlite3.connect(Path(path) if path else ops_db_path())
    try:
        con.execute(
            "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
            (_now(), status, run_id),
        )
        con.commit()
    finally:
        con.close()
    log.info("run_finished", run_id=run_id, status=status)


def log_evaluation(run_id: str, model_version: str, league: str,
                   protocol: str, window_start: str | None,
                   window_end: str | None, metric_name: str,
                   metric_value: float,
                   path: str | Path | None = None) -> None:
    """Write one metric value to the evaluations table."""
    con = sqlite3.connect(Path(path) if path else ops_db_path())
    try:
        con.execute(
            "INSERT INTO evaluations (run_id, model_version, league, protocol,"
            " window_start, window_end, metric_name, metric_value, evaluated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, model_version, league, protocol, window_start,
             window_end, metric_name, metric_value, _now()),
        )
        con.commit()
    finally:
        con.close()


def upsert_model_registry(model_version: str, league: str,
                          git_sha: str | None, feature_set_version: str | None,
                          data_hash: str | None, stage: str = "staging",
                          path: str | Path | None = None) -> None:
    """Insert or refresh a model_registry row. Re-fitting on the same day
    reuses the date-based version and just refreshes the row."""
    con = sqlite3.connect(Path(path) if path else ops_db_path())
    try:
        con.execute(
            "INSERT INTO model_registry (model_version, league, git_sha,"
            " feature_set_version, data_hash, created_at, stage)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(model_version) DO UPDATE SET"
            " git_sha = excluded.git_sha,"
            " feature_set_version = excluded.feature_set_version,"
            " data_hash = excluded.data_hash,"
            " created_at = excluded.created_at,"
            " stage = excluded.stage",
            (model_version, league, git_sha, feature_set_version, data_hash,
             _now(), stage),
        )
        con.commit()
    finally:
        con.close()
    log.info("model_registered", model_version=model_version, league=league,
             stage=stage)


def promote_model(league: str, version: str,
                  path: str | Path | None = None) -> bool:
    """Move `version` to production for `league`; the previous production
    row (if any) is demoted to archived. Never called automatically: the
    caller decides after comparing walk-forward metrics.

    Returns True when the version existed in the registry."""
    con = sqlite3.connect(Path(path) if path else ops_db_path())
    try:
        row = con.execute(
            "SELECT model_version FROM model_registry"
            " WHERE league = ? AND model_version = ?", (league, version)
        ).fetchone()
        if row is None:
            log.warning("promote_unknown_version", league=league, version=version)
            return False
        con.execute(
            "UPDATE model_registry SET stage = 'archived'"
            " WHERE league = ? AND stage = 'production'",
            (league,),
        )
        con.execute(
            "UPDATE model_registry SET stage = 'production'"
            " WHERE league = ? AND model_version = ?", (league, version)
        )
        con.commit()
    finally:
        con.close()
    log.info("model_promoted", league=league, version=version)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Init the ops ledger database.")
    parser.parse_args(argv)
    path = init_ops_db()
    log.info("ops_db_ready", path=str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
