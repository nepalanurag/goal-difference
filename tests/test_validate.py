"""Tests for etl.validate: the five contract checks + quarantine/report."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etl import validate
from etl.team_names import CANONICAL
from tests.helpers import make_season_df, tiny_frame

LEAGUE = "pl"


def _paths(tmp: Path, league: str = LEAGUE):
    return (tmp / f"fixtures_{league}.csv",
            tmp / f"quarantine_{league}.csv",
            tmp / "validation_report.json")


def _write(df: pd.DataFrame, tmp: Path, league: str = LEAGUE) -> tuple[Path, Path, Path]:
    fx, qx, rx = _paths(tmp, league)
    df.to_csv(fx, index=False)
    return fx, qx, rx


def _run(df: pd.DataFrame, tmp: Path, league: str = LEAGUE):
    fx, qx, rx = _write(df, tmp, league)
    return validate.validate_league(league, fx, qx, rx), fx, qx, rx


# ---------------------------------------------------------------- happy path

def test_valid_two_seasons_pass(tmp_path):
    df = pd.concat([make_season_df(LEAGUE, "2023"),
                    make_season_df(LEAGUE, "2024", start="2024-08-16")],
                   ignore_index=True)
    (ok, checks, offenders), _, _, _ = _run(df, tmp_path)
    assert ok is True
    assert len(offenders) == 0
    assert checks["finished_count"]["ok"] is True
    assert all(v["ok"] for v in checks.values())


def test_bundesliga_expects_306(tmp_path):
    df = make_season_df("bundesliga", "2023")
    assert len(df) == 306
    (ok, checks, _), _, _, _ = _run(df, tmp_path, "bundesliga")
    assert ok is True
    assert "306" in checks["finished_count"]["detail"]


# ---------------------------------------------------------------- count check

def test_short_season_fails_count_and_quarantines(tmp_path):
    df = make_season_df(LEAGUE, "2023").iloc[:-10]  # 370 finished, need 380
    (ok, checks, offenders), _, qx, _ = _run(df, tmp_path)
    assert ok is False
    assert checks["finished_count"]["ok"] is False
    assert len(offenders) == 370  # the whole suspect season block
    # quarantine + report written by main(); emulate via validate outputs
    offenders.to_csv(qx, index=False)
    assert len(pd.read_csv(qx)) == 370


def test_main_exit_code_and_report(tmp_path, monkeypatch):
    from etl.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    df = make_season_df(LEAGUE, "2023").iloc[:-10]
    df.to_csv(tmp_path / f"fixtures_{LEAGUE}.csv", index=False)
    assert validate.main(["--leagues", LEAGUE]) == 1
    report = json.loads((tmp_path / "validation_report.json").read_text())
    assert report[LEAGUE]["ok"] is False
    assert report[LEAGUE]["quarantined"] == 370
    assert report[LEAGUE]["checks"]["finished_count"]["ok"] is False
    assert len(pd.read_csv(tmp_path / f"quarantine_{LEAGUE}.csv")) == 370


def test_main_passes_on_good_data(tmp_path, monkeypatch):
    from etl.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    make_season_df(LEAGUE, "2023").to_csv(tmp_path / f"fixtures_{LEAGUE}.csv",
                                          index=False)
    assert validate.main(["--leagues", LEAGUE]) == 0
    report = json.loads((tmp_path / "validation_report.json").read_text())
    assert report[LEAGUE]["ok"] is True
    assert report[LEAGUE]["quarantined"] == 0


def test_missing_file_is_loud(tmp_path, monkeypatch):
    from etl.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert validate.main(["--leagues", LEAGUE]) == 1


# ---------------------------------------------------------------- row checks (season 2025: count check skipped)

def test_duplicate_ids(tmp_path):
    df = tiny_frame()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)  # dup fixture x-1
    (ok, checks, offenders), _, _, _ = _run(df, tmp_path)
    assert ok is False
    assert checks["duplicate_ids"]["ok"] is False
    assert set(offenders["fixture_id"]) == {"x-1"}
    assert len(offenders) == 2


def test_goals_must_match_status(tmp_path):
    df = tiny_frame()
    df.loc[0, "status"] = "scheduled"
    df.loc[0, ["home_goals", "away_goals"]] = [1, 1]  # goals but scheduled
    df.loc[1, ["home_goals", "away_goals"]] = [None, None]  # finished, no goals
    (ok, checks, offenders), _, _, _ = _run(df, tmp_path)
    assert ok is False
    assert checks["goals_iff_finished"]["ok"] is False
    assert len(offenders) == 2


def test_unknown_team(tmp_path):
    df = tiny_frame()
    df.loc[1, "away"] = "Not A Real Team"
    (ok, checks, offenders), _, _, _ = _run(df, tmp_path)
    assert ok is False
    assert checks["teams_in_set"]["ok"] is False
    assert list(offenders["fixture_id"]) == ["x-2"]
    assert "Not A Real Team" not in CANONICAL[LEAGUE]


def test_dates_must_not_step_backwards(tmp_path):
    df = tiny_frame()
    df.loc[1, "date"] = "2025-08-10"  # earlier than the row above it
    (ok, checks, offenders), _, _, _ = _run(df, tmp_path)
    assert ok is False
    assert checks["dates_non_decreasing"]["ok"] is False
    assert list(offenders["fixture_id"]) == ["x-2"]
