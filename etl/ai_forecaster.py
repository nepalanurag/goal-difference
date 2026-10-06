"""Weekly AI forecaster: the AI as the extra layer, not the predictions.

This module RUNS the already-fitted statistical (Poisson) and ML models from
etl.fit and writes their 1X2 probabilities to the per-league prediction
ledgers (etl.ledger). It never invents probabilities: every number in the
ledger and the memo comes from a fitted model, a real fixture result, or a
deterministic computation on those.

Weekly cycle per league:
  1. forecast: fit.predict_upcoming(league) -> ledger.append_predictions
     (rows already in the ledger are skipped, so re-runs are idempotent).
  2. score: any ledger rows still unscored get joined against finished
     fixtures in data/fixtures_{league}.csv and scored via ledger.score_league.
  3. memo: data/ai_memo_{YYYY-MM-DD}.md (plus data/ai_memo_latest.md) with
     walk-forward log-loss from the fitted params, ledger log-loss on the
     newly scored fixtures, a calibration summary, and a model-decay watch.
     The memo is labeled AI-generated.

Usage: python -m etl.ai_forecaster [--leagues pl laliga] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import fit, ledger
from .config import settings
from .logging_setup import get_logger

log = get_logger(__name__)

RESULT_MAP = {0: "away", 1: "draw", 2: "home"}


def _fixtures_df(league: str) -> pd.DataFrame:
    path = settings.data_dir / f"fixtures_{league}.csv"
    return pd.read_csv(path, parse_dates=["date"])


def _ledger_df(league: str) -> pd.DataFrame | None:
    path = settings.data_dir / f"predictions_ledger_{league}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, dtype={"fixture_date": str, "home": str,
                                    "away": str})


def _finished_results(league: str) -> pd.DataFrame:
    """Finished fixtures as ledger-keyed results (0/1/2)."""
    df = _fixtures_df(league)
    fin = df[df["status"] == "finished"].copy()
    fin["result"] = np.select(
        [fin["home_goals"] > fin["away_goals"],
         fin["home_goals"] == fin["away_goals"]],
        [2, 1], default=0)
    fin["fixture_date"] = pd.to_datetime(fin["date"]).dt.strftime("%Y-%m-%d")
    return fin[["fixture_date", "home", "away", "result"]].copy()


def forecast_league(league: str, dry_run: bool = False) -> int:
    """Predict upcoming fixtures with the fitted models; append to ledger."""
    preds = fit.predict_upcoming(league)
    if preds.empty:
        log.info("forecaster_no_upcoming", league=league)
        return 0
    preds = preds.copy()
    preds["fixture_date"] = pd.to_datetime(preds["date"]).dt.strftime("%Y-%m-%d")

    existing = _ledger_df(league)
    if existing is not None and not existing.empty:
        have = set(zip(existing["fixture_date"], existing["home"],
                       existing["away"]))
        preds = preds[[(r.fixture_date, r.home, r.away) not in have
                       for r in preds.itertuples()]]

    rows = [{
        "fixture_date": r.fixture_date, "home": r.home, "away": r.away,
        "p_home_poisson": float(r.p_home_poisson),
        "p_draw_poisson": float(r.p_draw_poisson),
        "p_away_poisson": float(r.p_away_poisson),
        "p_home_ml": float(r.p_home_ml), "p_draw_ml": float(r.p_draw_ml),
        "p_away_ml": float(r.p_away_ml),
        "p_home_ens": float(r.p_home_ens), "p_draw_ens": float(r.p_draw_ens),
        "p_away_ens": float(r.p_away_ens),
        "model_version": str(r.model_version),
    } for r in preds.itertuples()]

    if dry_run:
        log.info("forecaster_dry_run_append", league=league, n=len(rows))
        return len(rows)
    if not rows:
        log.info("forecaster_nothing_new", league=league)
        return 0
    return ledger.append_predictions(league, rows)


def score_unscored(league: str, dry_run: bool = False) -> dict:
    """Score ledger rows that have finished since the last run."""
    led = _ledger_df(league)
    if led is None or led.empty:
        return {"newly_scored": 0}
    led["result"] = pd.to_numeric(led.get("result"), errors="coerce")
    unscored = led[led["result"].isna()]
    if unscored.empty:
        return {"newly_scored": 0}

    results = _finished_results(league)
    if results.empty:
        log.warning("forecaster_no_finished", league=league)
        return {"newly_scored": 0}

    keys_before = set(zip(led["fixture_date"], led["home"], led["away"]))
    match = results[[tuple(k) in keys_before
                     for k in zip(results["fixture_date"],
                                  results["home"], results["away"])]]
    if dry_run:
        log.info("forecaster_dry_run_score", league=league,
                 n_matches=len(match))
        return {"newly_scored": len(match)}

    scored = ledger.score_league(league, results)
    scored["result"] = pd.to_numeric(scored["result"], errors="coerce")
    new = scored[(scored["result"].notna()) &
                 (scored["fixture_date"].astype(str) + "|"
                  + scored["home"].astype(str) + "|"
                  + scored["away"].astype(str)).isin(
                      match["fixture_date"] + "|" + match["home"] + "|"
                      + match["away"])]
    stats = {"newly_scored": int(len(new))}
    for suffix in ("poisson", "ml", "ens"):
        col = f"logloss_{suffix}"
        if col in new.columns and len(new):
            stats[col] = float(new[col].astype(float).mean())
    log.info("forecaster_scored", league=league, **stats)
    return stats


def _walkforward_table(leagues: list[str]) -> dict:
    out = {}
    for league in leagues:
        path = settings.data_dir / f"params_{league}.json"
        if not path.exists():
            log.warning("forecaster_no_params", league=league)
            continue
        params = json.loads(path.read_text())
        wf = params.get("walkforward", {})
        out[league] = {
            "chosen_ml": params.get("chosen_ml"),
            "model_version": params.get("model_version"),
            "fit_date": params.get("fit_date"),
            "poisson": (wf.get("poisson") or {}).get("logloss"),
            "ml": (wf.get(params.get("chosen_ml", "")) or {}).get("logloss"),
            "ensemble": (wf.get("ensemble") or {}).get("logloss"),
            "baseline": (wf.get("baseline") or {}).get("logloss"),
        }
    return out


def _calibration_summary(league: str) -> pd.DataFrame:
    led = _ledger_df(league)
    if led is None or led.empty:
        return pd.DataFrame()
    led = led.copy()
    led["result"] = pd.to_numeric(led.get("result"), errors="coerce")
    scored = led[led["result"].notna()]
    if scored.empty:
        return pd.DataFrame()
    ens = scored[[f"p_{s}_ens" for s in ("home", "draw", "away")]].astype(float)
    # p_{side}_ens -> 0/1/2 via RESULT_MAP inversion
    side_code = {v: k for k, v in RESULT_MAP.items()}
    pred_side = ens.idxmax(axis=1).map(lambda c: side_code[c.split("_")[1]])
    scored = scored.assign(p_pred=ens.max(axis=1),
                           pred_side=pred_side,
                           hit=(pred_side.to_numpy()
                                == scored["result"].astype(int).to_numpy()))
    bands = (scored["calibration_band"].fillna("unknown")
             if "calibration_band" in scored.columns
             else pd.Series(["unknown"] * len(scored)))
    return (scored.assign(band=bands).groupby("band")
            .agg(n=("p_pred", "size"),
                 mean_p_pred=("p_pred", "mean"),
                 hit_rate=("hit", "mean")).reset_index()
            .sort_values("band"))


def _ledger_overall_logloss(league: str) -> dict:
    """Mean log-loss over ALL scored rows in the ledger, per model."""
    led = _ledger_df(league)
    if led is None or led.empty:
        return {}
    led = led.copy()
    led["result"] = pd.to_numeric(led.get("result"), errors="coerce")
    scored = led[led["result"].notna()]
    out: dict = {"n_scored": int(len(scored))}
    for suffix in ("poisson", "ml", "ens"):
        col = f"logloss_{suffix}"
        if col in scored.columns and len(scored):
            out[col] = float(scored[col].astype(float).mean())
    return out


def build_memo(leagues: list[str], score_stats: dict,
               run_date: date) -> str:
    """Compose the weekly memo markdown from real numbers only."""
    lines = [
        f"# Weekly AI forecast memo — {run_date.isoformat()}",
        "",
        "> AI-generated. All numbers below come from the fitted models and",
        "> real fixture results; nothing here was invented by the AI.",
        "",
        "## 1. Walk-forward log-loss (fitted models)",
        "",
        "| league | model version | poisson | ML (chosen) | ensemble | baseline |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    wf_table = _walkforward_table(leagues)
    for league in leagues:
        t = wf_table.get(league, {})
        fmt = lambda v: f"{v:.4f}" if v is not None else "n/a"  # noqa: E731
        lines.append(
            f"| {league} | {t.get('model_version', 'n/a')} | "
            f"{fmt(t.get('poisson'))} | {fmt(t.get('ml'))} "
            f"({t.get('chosen_ml', 'n/a')}) | {fmt(t.get('ensemble'))} | "
            f"{fmt(t.get('baseline'))} |")
    lines += ["", "## 2. Ledger scoring this run", "",
              "| league | newly scored | logloss poisson | logloss ML | "
              "logloss ensemble |",
              "| --- | --- | --- | --- | --- |"]
    for league in leagues:
        s = score_stats.get(league, {})
        fmt = lambda v: f"{v:.4f}" if v is not None else "n/a"  # noqa: E731
        lines.append(f"| {league} | {s.get('newly_scored', 0)} | "
                     f"{fmt(s.get('logloss_poisson'))} | "
                     f"{fmt(s.get('logloss_ml'))} | "
                     f"{fmt(s.get('logloss_ens'))} |")
    lines += ["", "## 3. Calibration (all scored fixtures)", ""]
    for league in leagues:
        cal = _calibration_summary(league)
        lines.append(f"### {league}")
        if cal.empty:
            lines.append("No scored fixtures yet.")
        else:
            lines.append("| band | n | mean P(predicted outcome) | hit rate |")
            lines.append("| --- | --- | --- | --- |")
            for r in cal.itertuples():
                lines.append(f"| {r.band} | {r.n} | {r.mean_p_pred:.3f} | "
                             f"{r.hit_rate:.3f} |")
        lines.append("")
    lines += ["## 4. Model-decay watch", ""]
    lines.append("Compares the ledger's overall ensemble log-loss against the "
                 "walk-forward ensemble log-loss. Flagged when the ledger is "
                 "worse by more than 0.05.")
    lines.append("")
    any_flag = False
    for league in leagues:
        overall = _ledger_overall_logloss(league)
        wf_ens = (wf_table.get(league) or {}).get("ensemble")
        led_ens = overall.get("logloss_ens")
        if wf_ens is None or led_ens is None:
            lines.append(f"- {league}: not enough scored data yet.")
            continue
        delta = led_ens - wf_ens
        flag = "DECAY FLAG" if delta > 0.05 else "ok"
        if delta > 0.05:
            any_flag = True
        lines.append(f"- {league}: ledger {led_ens:.4f} vs walk-forward "
                     f"{wf_ens:.4f} (delta {delta:+.4f}, "
                     f"n={overall['n_scored']}) — {flag}.")
    if any_flag:
        lines += ["",
                  "One or more leagues are flagged. The weekly memo should "
                  "investigate before the next refresh: check for distribution "
                  "shift (new season, promoted teams) or stale features."]
    lines += ["", "---",
              "_Produced by etl.ai_forecaster — AI as the extra layer over "
              "the fitted statistical and ML models._"]
    return "\n".join(lines)


def run(leagues: list[str], dry_run: bool = False) -> dict:
    run_date = date.today()
    score_stats: dict[str, dict] = {}
    for league in leagues:
        try:
            n = forecast_league(league, dry_run=dry_run)
            stats = score_unscored(league, dry_run=dry_run)
            stats["predictions_appended"] = n
            score_stats[league] = stats
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            log.error("forecaster_league_failed", league=league,
                      error=str(exc))
            score_stats[league] = {"error": str(exc)}
    if dry_run:
        log.info("forecaster_dry_run_done", leagues=leagues)
        return score_stats
    memo = build_memo(leagues, score_stats, run_date)
    memo_path = settings.data_dir / f"ai_memo_{run_date.isoformat()}.md"
    latest_path = settings.data_dir / "ai_memo_latest.md"
    memo_path.write_text(memo)
    latest_path.write_text(memo)
    log.info("memo_written", path=str(memo_path),
             latest=str(latest_path))
    return score_stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Weekly AI forecaster: run fitted models, score ledgers, "
                    "write the AI memo.")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        choices=settings.league_order,
                        help="league slugs (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="run end to end without writing ledgers or memos")
    args = parser.parse_args(argv)
    run(args.leagues, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
