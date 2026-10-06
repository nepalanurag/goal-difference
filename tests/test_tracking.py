"""Tests for etl.storage experiment tracking: runs, evaluations, registry."""
from __future__ import annotations

import sqlite3

from etl import storage


def _con(db_path):
    return sqlite3.connect(db_path)


def test_migration_931_creates_tables(tmp_path):
    db = tmp_path / "ops.sqlite"
    storage.init_ops_db(db)
    con = _con(db)
    try:
        tables = {r[0] for r in
                  con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"runs", "evaluations", "model_registry",
                "schema_migrations"} <= tables
        applied = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
        assert "9.3.1" in applied
    finally:
        con.close()
    # Idempotent: second init is a no-op.
    storage.init_ops_db(db)
    con = _con(db)
    try:
        applied = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
        assert list(applied).count("9.3.1") == 1
    finally:
        con.close()


def test_run_lifecycle(tmp_path):
    db = tmp_path / "ops.sqlite"
    storage.init_ops_db(db)
    run_id = storage.start_run(
        "pl", {"seed": 42}, seed=42, data_hash="abc123",
        feature_set_version="deadbeef", git_sha="sha1", path=db)
    storage.finish_run(run_id, "finished", path=db)
    con = _con(db)
    try:
        row = con.execute(
            "SELECT git_sha, league, seed, data_hash, feature_set_version,"
            " status, started_at, finished_at FROM runs WHERE run_id = ?",
            (run_id,)).fetchone()
    finally:
        con.close()
    assert row == ("sha1", "pl", 42, "abc123", "deadbeef", "finished",
                   row[6], row[7])
    assert row[6] is not None and row[7] is not None  # timestamps set


def test_evaluations_roundtrip(tmp_path):
    db = tmp_path / "ops.sqlite"
    storage.init_ops_db(db)
    run_id = storage.start_run("pl", {}, seed=42, data_hash=None,
                               feature_set_version=None, path=db)
    storage.log_evaluation(run_id, "v2026-10-06", "pl",
                           "walkforward-expanding-5fold",
                           "2023-08-01", "2026-05-01",
                           "ensemble:logloss", 0.987, path=db)
    storage.log_evaluation(run_id, "v2026-10-06", "pl",
                           "walkforward-expanding-5fold",
                           "2023-08-01", "2026-05-01",
                           "baseline:accuracy", 0.45, path=db)
    con = _con(db)
    try:
        rows = con.execute(
            "SELECT metric_name, metric_value FROM evaluations"
            " WHERE run_id = ? ORDER BY eval_id", (run_id,)).fetchall()
    finally:
        con.close()
    assert rows == [("ensemble:logloss", 0.987), ("baseline:accuracy", 0.45)]


def test_registry_upsert_and_promote(tmp_path):
    db = tmp_path / "ops.sqlite"
    storage.init_ops_db(db)
    storage.upsert_model_registry("v1", "pl", "sha1", "fv1", "dh1",
                                  stage="staging", path=db)
    # Refit same version: row refreshes, no duplicate.
    storage.upsert_model_registry("v1", "pl", "sha2", "fv1", "dh2",
                                  stage="staging", path=db)
    assert storage.promote_model("pl", "v1", path=db) is True
    storage.upsert_model_registry("v2", "pl", "sha3", "fv2", "dh3",
                                  stage="staging", path=db)
    assert storage.promote_model("pl", "v2", path=db) is True
    con = _con(db)
    try:
        stages = dict(con.execute(
            "SELECT model_version, stage FROM model_registry"
            " WHERE league = 'pl'").fetchall())
        count = con.execute(
            "SELECT COUNT(*) FROM model_registry WHERE model_version = 'v1'"
        ).fetchone()[0]
    finally:
        con.close()
    assert stages == {"v1": "archived", "v2": "production"}
    assert count == 1
    # Unknown version: no-op, returns False.
    assert storage.promote_model("pl", "nope", path=db) is False


def test_versioned_feature_path_naming():
    p = storage.features_lake_versioned_path("pl", "deadbeef")
    assert p.name == "features_vdeadbeef.parquet"
    assert p.parent.name == "pl"
    assert p.parent.parent.name == "features"
