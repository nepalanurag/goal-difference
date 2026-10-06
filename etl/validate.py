"""Validate: contract checks per league over data/fixtures_{league}.csv.

Checks, per league:
  schema                    pandera column checks (types, formats, enums)
  finished_count            finished fixtures per completed season (2023,
                            2024) match the league size: 380 for 20-team
                            leagues, 306 for Bundesliga (18 teams)
  duplicate_ids             no duplicate fixture_id
  goals_iff_finished        home_goals/away_goals present iff finished
  teams_in_set              home/away in the league's canonical team set
  dates_non_decreasing      dates never step backwards down the file

On failure the offending rows go to data/quarantine_{league}.csv, the
per-league outcome lands in data/validation_report.json, the failure is
logged loudly, and the process exits non-zero.

Usage:
    python -m etl.validate [--leagues pl laliga bundesliga seriea ligue1]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import pandera as pa
from pandera import Check, Column, DataFrameSchema

from .config import settings
from .logging_setup import get_logger
from .team_names import CANONICAL

log = get_logger(__name__)

# Only these seasons are complete; 2025 is CSV-only history-in-progress and
# 2026 is the live season, so neither gets the finished-count check.
COMPLETED_SEASONS = ("2023", "2024")
SEASONS = ("2023", "2024", "2025", "2026")
STATUSES = ("finished", "scheduled")
PROVENANCES = ("api_football", "csv_download", "csv_cached", "fpl_api",
               "schedule_reconstructed")

schema = DataFrameSchema(
    {
        "fixture_id": Column(str, nullable=False, coerce=True),
        "date": Column(str, Check.str_matches(r"^\d{4}-\d{2}-\d{2}$"),
                       nullable=False, coerce=True),
        "season": Column(str, Check.isin(SEASONS), nullable=False, coerce=True),
        "league": Column(str, nullable=False, coerce=True),
        "home": Column(str, nullable=False, coerce=True),
        "away": Column(str, nullable=False, coerce=True),
        "home_goals": Column(float, nullable=True, coerce=True),
        "away_goals": Column(float, nullable=True, coerce=True),
        "status": Column(str, Check.isin(STATUSES), nullable=False, coerce=True),
        "provenance": Column(str, Check.isin(PROVENANCES), nullable=False,
                             coerce=True),
        "api_fixture_id": Column(object, nullable=True, coerce=True),
    },
    strict=False,  # allow the nullable stat columns from the contract
)


def _check_finished_count(df: pd.DataFrame, league: str):
    n_teams = settings.leagues[league]["n_teams"]
    expected = n_teams * (n_teams - 1)
    offenders = pd.Index([])
    details = []
    ok = True
    for season in COMPLETED_SEASONS:
        block = df[df["season"] == season]
        if block.empty:
            details.append(f"{season}: absent, skipped")
            continue
        n = int((block["status"] == "finished").sum())
        if n != expected:
            ok = False
            offenders = offenders.union(
                block.index[block["status"] == "finished"])
            details.append(f"{season}: {n} finished, expected {expected}")
        else:
            details.append(f"{season}: {n} finished, ok")
    return ok, "; ".join(details), offenders


def _check_duplicate_ids(df: pd.DataFrame):
    dup = df.duplicated(subset=["fixture_id"], keep=False)
    n = int(dup.sum())
    return n == 0, f"{n} duplicate fixture_id rows", df.index[dup]


def _check_goals_iff_finished(df: pd.DataFrame):
    both = df["home_goals"].notna() & df["away_goals"].notna()
    finished = df["status"] == "finished"
    bad = finished != both
    n = int(bad.sum())
    return n == 0, f"{n} rows where goals do not match status", df.index[bad]


def _check_teams_in_set(df: pd.DataFrame, league: str):
    teams = CANONICAL[league]
    bad = ~df["home"].isin(teams) | ~df["away"].isin(teams)
    n = int(bad.sum())
    return n == 0, f"{n} rows with a team outside the canonical set", df.index[bad]


def _check_dates_non_decreasing(df: pd.DataFrame):
    dates = pd.to_datetime(df["date"], errors="coerce")
    prev = dates.shift(1)
    bad = dates.isna() | (dates < prev)
    if len(bad):
        bad.iloc[0] = dates.isna().iloc[0]  # first row has no predecessor
    n = int(bad.sum())
    return n == 0, f"{n} rows where the date steps backwards", df.index[bad]


def validate_league(
    league: str,
    fixtures_path: Path | None = None,
    quarantine_path: Path | None = None,
    report_path: Path | None = None,
) -> tuple[bool, dict, pd.DataFrame]:
    """Validate one league. Returns (ok, checks, offender_rows)."""
    fixtures_path = fixtures_path or settings.data_dir / f"fixtures_{league}.csv"
    quarantine_path = quarantine_path or settings.data_dir / f"quarantine_{league}.csv"
    report_path = report_path or settings.data_dir / "validation_report.json"

    if league not in settings.leagues:
        raise ValueError(f"unknown league: {league}")
    if not fixtures_path.exists():
        raise FileNotFoundError(f"fixtures file not found: {fixtures_path}")

    raw = pd.read_csv(fixtures_path)
    checks: dict[str, dict] = {}

    if raw.empty:
        checks["has_rows"] = {"ok": False, "detail": "fixtures file is empty"}
        return False, checks, raw

    try:
        df = schema.validate(raw, lazy=True)  # coerced copy for the checks
        checks["schema"] = {"ok": True, "detail": "pandera schema passed"}
        schema_ok = True
    except pa.errors.SchemaError as exc:
        checks["schema"] = {"ok": False, "detail": str(exc)[:500]}
        schema_ok = False
    except pa.errors.SchemaErrors as exc:
        n = len(exc.failure_cases)
        checks["schema"] = {"ok": False, "detail": f"{n} schema failures"}
        schema_ok = False

    offender_idx = pd.Index([])
    if schema_ok:
        for name, fn, *extra in [
            ("finished_count", _check_finished_count, league),
            ("duplicate_ids", _check_duplicate_ids),
            ("goals_iff_finished", _check_goals_iff_finished),
            ("teams_in_set", _check_teams_in_set, league),
            ("dates_non_decreasing", _check_dates_non_decreasing),
        ]:
            ok, detail, bad_idx = fn(df, *extra)
            checks[name] = {"ok": bool(ok), "detail": detail}
            offender_idx = offender_idx.union(bad_idx)
    else:
        for name in ("finished_count", "duplicate_ids", "goals_iff_finished",
                     "teams_in_set", "dates_non_decreasing"):
            checks[name] = {"ok": False, "detail": "skipped: schema failed"}

    offenders = raw.loc[sorted(set(offender_idx))] if len(offender_idx) else raw.iloc[0:0]
    ok = all(c["ok"] for c in checks.values())
    return ok, checks, offenders


def _write_outputs(league: str, ok: bool, checks: dict,
                   offenders: pd.DataFrame,
                   quarantine_path: Path, report_path: Path) -> None:
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    offenders.to_csv(quarantine_path, index=False)

    report: dict = {}
    if report_path.exists():
        report = json.loads(report_path.read_text())
    report[league] = {
        "ok": ok,
        "checks": checks,
        "quarantined": int(len(offenders)),
    }
    report_path.write_text(json.dumps(report, indent=2))

    if ok:
        log.info("validation_passed", league=league,
                 checks={k: v["ok"] for k, v in checks.items()})
    else:
        failed = [k for k, v in checks.items() if not v["ok"]]
        log.error("VALIDATION FAILED", league=league, failed_checks=failed,
                  quarantined=int(len(offenders)),
                  quarantine_file=str(quarantine_path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        help="league slugs (default: all)")
    args = parser.parse_args(argv)

    exit_code = 0
    for league in args.leagues:
        q_path = settings.data_dir / f"quarantine_{league}.csv"
        r_path = settings.data_dir / "validation_report.json"
        try:
            ok, checks, offenders = validate_league(league, quarantine_path=q_path,
                                                    report_path=r_path)
        except (FileNotFoundError, ValueError) as exc:
            log.error("validation_error", league=league, error=str(exc))
            return 1
        _write_outputs(league, ok, checks, offenders, q_path, r_path)
        if not ok:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
