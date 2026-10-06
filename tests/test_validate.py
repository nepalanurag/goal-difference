"""Tests for etl.validate: the five contract checks + quarantine/report."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from etl import validate
from etl.config import settings
from etl.team_names import CANONICAL
from tests.helpers import ALL_COLS, STAT_COLS, make_season_df, tiny_frame

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


# ---------------------------------------------------------------- new gates (9.1)

def _live_frame(n_finished=4, last_played_offset=2, next_offset=7,
                home_goals=2, away_goals=1, scheduled=True):
    """Small live-season frame with dates relative to today (no rot)."""
    season = settings.live_season
    teams = sorted(CANONICAL[LEAGUE])[:4]
    today = date.today()
    rows = []
    for i in range(n_finished):
        d = today - timedelta(days=last_played_offset + (n_finished - 1 - i))
        rows.append({
            "fixture_id": f"live-f-{i}", "date": d.isoformat(),
            "season": season, "league": LEAGUE,
            "home": teams[0], "away": teams[1],
            "home_goals": home_goals, "away_goals": away_goals,
            "status": "finished", "provenance": "csv_cached",
            "api_fixture_id": None,
        })
    if scheduled:
        rows.append({
            "fixture_id": "live-s-0",
            "date": (today + timedelta(days=next_offset)).isoformat(),
            "season": season, "league": LEAGUE,
            "home": teams[2], "away": teams[3],
            "home_goals": None, "away_goals": None,
            "status": "scheduled", "provenance": "csv_cached",
            "api_fixture_id": None,
        })
    for r in rows:
        r.update({c: None for c in STAT_COLS})
    return pd.DataFrame(rows, columns=ALL_COLS)


def test_freshness_passes_when_live_season_covers_today(tmp_path):
    df = _live_frame()
    (ok, checks, _), _, _, _ = _run(df, tmp_path)
    assert checks["freshness"]["ok"] is True
    assert ok is True


def test_freshness_tolerates_a_scheduled_break(tmp_path):
    # Last played 16d ago (international break) but next fixture 4d ahead:
    # the pipeline's view of the present is current.
    df = _live_frame(last_played_offset=16, next_offset=4)
    (ok, checks, _), _, _, _ = _run(df, tmp_path)
    assert checks["freshness"]["ok"] is True
    assert ok is True


def test_freshness_fails_when_live_season_is_stale(tmp_path):
    df = _live_frame(last_played_offset=60, scheduled=False)
    (ok, checks, _), _, _, _ = _run(df, tmp_path)
    assert ok is False
    assert checks["freshness"]["ok"] is False


def test_freshness_skipped_without_live_season(tmp_path):
    df = make_season_df(LEAGUE, "2023")  # completed seasons only
    (ok, checks, _), _, _, _ = _run(df, tmp_path)
    assert checks["freshness"]["ok"] is True
    assert "skipped" in checks["freshness"]["detail"]


def test_row_count_band_passes_within_band(tmp_path):
    df = _live_frame()
    fx, qx, rx = _write(df, tmp_path)
    (tmp_path / "validation_reference.json").write_text(
        json.dumps({"pl": len(df)}))
    ok, checks, _ = validate.validate_league(LEAGUE, fx, qx, rx)
    assert checks["row_count_band"]["ok"] is True
    assert ok is True


def test_row_count_band_fails_outside_band(tmp_path):
    df = _live_frame()
    fx, qx, rx = _write(df, tmp_path)
    (tmp_path / "validation_reference.json").write_text(
        json.dumps({"pl": len(df) * 10}))
    ok, checks, _ = validate.validate_league(LEAGUE, fx, qx, rx)
    assert ok is False
    assert checks["row_count_band"]["ok"] is False


def test_row_count_band_skipped_without_reference(tmp_path):
    df = _live_frame()
    (ok, checks, _), _, _, _ = _run(df, tmp_path)
    assert checks["row_count_band"]["ok"] is True
    assert "skipped" in checks["row_count_band"]["detail"]


def test_goal_distribution_passes_on_sane_means(tmp_path):
    df = _live_frame()
    (ok, checks, _), _, _, _ = _run(df, tmp_path)
    assert checks["goal_distribution"]["ok"] is True
    assert ok is True


def test_goal_distribution_fails_on_absurd_means(tmp_path):
    df = _live_frame(home_goals=5, away_goals=5)
    (ok, checks, _), _, _, _ = _run(df, tmp_path)
    assert ok is False
    assert checks["goal_distribution"]["ok"] is False
