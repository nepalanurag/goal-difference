"""Per-league prediction ledgers at data/predictions_ledger_{league}.csv.

Lifecycle:
  init    create the empty ledger (header only)
  append  add one row per fixture with the three models' 1X2 probabilities
  score   join actual results, append result + log-loss per model +
          a calibration band (decile of the ensemble's predicted-outcome
          probability, e.g. "0.5-0.6")

result encoding: 0 = away win, 1 = draw, 2 = home win.
Probabilities are clipped to [1e-6, 1 - 1e-6] before log-loss.

Usage:
    python -m etl.ledger --init [--leagues pl laliga]
    python -m etl.ledger --score --results data/results_pl.csv [--leagues pl]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .config import settings
from .logging_setup import get_logger

log = get_logger(__name__)

LEDGER_COLS = [
    "fixture_date", "home", "away",
    "p_home_poisson", "p_draw_poisson", "p_away_poisson",
    "p_home_ml", "p_draw_ml", "p_away_ml",
    "p_home_ens", "p_draw_ens", "p_away_ens",
    "model_version",
]
SCORE_COLS = ["result", "logloss_poisson", "logloss_ml", "logloss_ens",
              "calibration_band"]
KEY_COLS = ["fixture_date", "home", "away"]

EPS = 1e-6
RESULT_TO_PROB = {0: "away", 1: "draw", 2: "home"}


def _ledger_path(league: str, path: Path | None = None) -> Path:
    if path is not None:
        return path
    if league not in settings.leagues:
        raise ValueError(f"unknown league: {league}")
    return settings.data_dir / f"predictions_ledger_{league}.csv"


def init_ledger(league: str, path: Path | None = None) -> Path:
    """Create the empty ledger file. Leaves an existing ledger untouched."""
    ledger_path = _ledger_path(league, path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.exists():
        log.warning("ledger_exists", league=league, path=str(ledger_path))
        return ledger_path
    pd.DataFrame(columns=LEDGER_COLS).to_csv(ledger_path, index=False)
    log.info("ledger_initialized", league=league, path=str(ledger_path))
    return ledger_path


def _read_ledger(ledger_path: Path) -> pd.DataFrame:
    if not ledger_path.exists():
        raise FileNotFoundError(f"ledger not found: {ledger_path} (run --init)")
    return pd.read_csv(ledger_path, dtype={c: str for c in KEY_COLS})


def append_predictions(league: str, rows: list[dict],
                       path: Path | None = None) -> int:
    """Append prediction rows. Each row must carry fixture_date/home/away."""
    for i, row in enumerate(rows):
        missing = [c for c in KEY_COLS if c not in row]
        if missing:
            raise ValueError(f"row {i} missing keys: {missing}")
    ledger_path = init_ledger(league, path)
    new = pd.DataFrame(rows).reindex(columns=LEDGER_COLS)
    new.to_csv(ledger_path, mode="a", header=False, index=False)
    log.info("predictions_appended", league=league, n=len(new),
             path=str(ledger_path))
    return len(new)


def _logloss(probs: pd.DataFrame, results: pd.Series, suffix: str) -> pd.Series:
    """Natural-log loss of one model's 1X2 probabilities vs the result."""
    outcome = results.astype(int).map(RESULT_TO_PROB)  # 0/1/2 -> away/draw/home
    picked = pd.Series(np.nan, index=probs.index)
    for code, side in RESULT_TO_PROB.items():
        col = f"p_{side}_{suffix}"
        picked = picked.where(outcome != side,
                              probs[col].astype(float).clip(EPS, 1 - EPS))
    return -np.log(picked)


def _calibration_band(ens: pd.DataFrame) -> pd.Series:
    top = ens[[f"p_{s}_ens" for s in ("home", "draw", "away")]].astype(float).max(axis=1)
    lo = np.floor(top.fillna(-1) * 10).clip(0, 9).astype("int64") / 10
    band = lo.map(lambda x: f"{x:.1f}-{x + 0.1:.1f}")
    return band.where(top.notna(), "unknown")


def score_league(league: str, results: pd.DataFrame,
                 path: Path | None = None) -> pd.DataFrame:
    """Join results onto the ledger and write back the scored columns."""
    ledger_path = _ledger_path(league, path)
    ledger = _read_ledger(ledger_path)

    needed = KEY_COLS + ["result"]
    missing = [c for c in needed if c not in results.columns]
    if missing:
        raise ValueError(f"results missing columns: {missing}")

    res = results[needed].copy()
    res[KEY_COLS] = res[KEY_COLS].astype(str)
    # Drop ledger's result column before merge to avoid result_x/result_y;
    # the incoming results are the source of truth.
    ledger_nores = ledger.drop(columns=["result"], errors="ignore")
    merged = ledger_nores.merge(res, on=KEY_COLS, how="left", indicator=True)

    unmatched = res.merge(ledger[KEY_COLS], on=KEY_COLS, how="left",
                          indicator=True)
    n_unmatched = int((unmatched["_merge"] == "left_only").sum())
    if n_unmatched:
        log.warning("results_without_predictions", league=league,
                    n=n_unmatched)

    scored = merged.drop(columns=["_merge"]).copy()
    for col in ("logloss_poisson", "logloss_ml", "logloss_ens"):
        if col not in scored.columns:
            scored[col] = np.nan
    if "calibration_band" not in scored.columns:
        scored["calibration_band"] = pd.Series(
            ["unknown"] * len(scored), dtype=object)
    has_result = scored["result"].notna()
    for suffix in ("poisson", "ml", "ens"):
        scored.loc[has_result, f"logloss_{suffix}"] = _logloss(
            scored.loc[has_result], scored.loc[has_result, "result"], suffix)
    scored.loc[has_result, "calibration_band"] = _calibration_band(
        scored.loc[has_result])

    scored.to_csv(ledger_path, index=False)
    n = int(has_result.sum())
    log.info("ledger_scored", league=league, scored=n, total=len(scored))
    return scored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true", help="create empty ledgers")
    group.add_argument("--score", action="store_true",
                       help="score ledgers against a results CSV")
    parser.add_argument("--results", type=Path, default=None,
                        help="results CSV (required with --score)")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        help="league slugs (default: all)")
    args = parser.parse_args(argv)

    if args.score and args.results is None:
        parser.error("--score requires --results")

    for league in args.leagues:
        try:
            if args.init:
                init_ledger(league)
            else:
                results = pd.read_csv(args.results,
                                      dtype={c: str for c in KEY_COLS})
                results["result"] = results["result"].astype(int)
                score_league(league, results)
        except (FileNotFoundError, ValueError) as exc:
            log.error("ledger_error", league=league, error=str(exc))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
