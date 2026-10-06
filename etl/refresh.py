"""Refresh: the daily matchday updater (also the GitHub Action entrypoint).

Steps:
  1. Pull latest finished fixtures (FPL for PL, current-season CSVs for all).
  2. Accumulate European fixtures via api-football date queries.
  3. Refresh team news (FPL for PL; lineup-based absence detection for others).
  4. Hash the finished-fixture set across all 5 leagues; compare with
     data/last_refresh.json. Unchanged -> exit 0 quietly.
  5. Changed -> full rebuild: extract -> validate -> features -> fit ->
     simulate -> ledgers -> site, then the caller commits docs/ + data/.

Only keyless sources are used except the api-football European accumulation
(~9 requests/day via the API_FOOTBALL_KEY repo secret in CI).

Usage: python -m etl.refresh [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from .config import settings
from .logging_setup import get_logger
from .storage import finish_ingest_run, init_ops_db, start_ingest_run

log = get_logger(__name__)

PIPELINE = [
    (["extract"], "extract"),
    (["validate"], "validate"),
    (["features"], "features"),
    (["h2h"], "h2h"),
    (["players"], "players"),
    (["team_news"], "team_news"),
    (["fit"], "fit"),
    (["simulate"], "simulate"),
    (["ai_forecaster"], "ai_forecaster"),  # appends to ledgers + scores + memo
    (["build_site"], "build_site"),
]


def finished_hash() -> str:
    """Hash of the finished-fixture set across all leagues (ids + scores)."""
    h = hashlib.sha1()
    for league in settings.league_order:
        path = settings.data_dir / f"fixtures_{league}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        fin = df[df["status"] == "finished"][
            ["fixture_id", "home_goals", "away_goals"]].sort_values("fixture_id")
        h.update(fin.to_csv(index=False).encode())
    return h.hexdigest()[:16]


def run_module(args: list[str]) -> None:
    cmd = [sys.executable, "-m", f"etl.{args[0]}", *args[1:]]
    log.info("pipeline_step", module=args[0])
    proc = subprocess.run(cmd, cwd=settings.repo_root, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"etl.{args[0]} failed (exit {proc.returncode})")


def _fixture_row_total() -> int:
    total = 0
    for league in settings.league_order:
        path = settings.data_dir / f"fixtures_{league}.csv"
        if path.exists():
            total += sum(1 for _ in path.open()) - 1  # minus header
    return total


def _refresh(args: argparse.Namespace) -> tuple[int, str]:
    """Run the pipeline body. Returns (exit_code, notes)."""
    # Steps 1-3: fresh pulls (extract handles FPL + CSVs + European + lineups;
    # players/team_news refresh their keyless sources).
    for mod in (["extract"], ["players"], ["team_news"]):
        run_module(mod)

    new_hash = finished_hash()
    state_path = settings.data_dir / "last_refresh.json"
    old = json.loads(state_path.read_text()) if state_path.exists() else {}
    if not args.force and old.get("finished_hash") == new_hash:
        log.info("refresh_noop", finished_hash=new_hash)
        return 0, "noop: finished-fixture hash unchanged"

    log.info("refresh_changed", old_hash=old.get("finished_hash"),
             new_hash=new_hash)
    for step in PIPELINE[3:]:  # extract already ran above
        run_module(step[0])

    state_path.write_text(json.dumps({
        "finished_hash": new_hash,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "date": date.today().isoformat(),
    }, indent=1))
    log.info("refresh_done", finished_hash=new_hash)
    return 0, f"rebuilt: finished_hash={new_hash}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hash-gated daily refresh.")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild even if the fixture hash is unchanged.")
    args = parser.parse_args(argv)

    init_ops_db()
    run_id = start_ingest_run(notes=f"refresh argv={argv or []}")
    rows_in = _fixture_row_total()
    try:
        code, notes = _refresh(args)
    except Exception as exc:  # noqa: BLE001 - record then re-raise
        finish_ingest_run(run_id, "failed", rows_in=rows_in,
                          notes=f"{type(exc).__name__}: {exc}"[:500])
        raise
    finish_ingest_run(run_id, "finished", rows_in=rows_in,
                      rows_out=_fixture_row_total(), notes=notes)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
