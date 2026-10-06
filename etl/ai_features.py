"""AI feature ideation: candidate features behind flags, time-respecting ablation.

The agent proposes, the human vets. Each candidate carries a hypothesis and
an implementation as a function of the existing (shift(1)-lagged, so
time-safe) feature row. Nothing is ever enabled by default: every entry in
CANDIDATES has "enabled": False and the ablation reports a verdict per
candidate (keep / kill / needs-human-review).

Ablation protocol: for one league (default pl), re-run a SHORT walk-forward
(2 TimeSeriesSplit splits) of the Poisson model only, once for the baseline
feature set and once per candidate with that candidate's columns added.
Delta log-loss (candidate - baseline) is the score; negative is better.

Runtime is kept modest by reusing etl.fit.PoissonModel and
etl.features.build_features and skipping the ML walk-forward here.

Usage: python -m etl.ai_features [--league pl] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss
from sklearn.model_selection import TimeSeriesSplit

from . import fit
from .config import settings
from .features import build_features
from .logging_setup import get_logger

log = get_logger(__name__)

LABELS = [0, 1, 2]  # away, draw, home

# Verdict thresholds on delta log-loss (candidate - baseline).
KEEP_THRESHOLD = -0.005   # improves by more than this -> recommend keep
KILL_THRESHOLD = 0.005    # worse by more than this -> recommend kill


def _rest_days_sq(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Nonlinear fatigue: exhaustion rises faster than linearly with short rest."""
    return {
        "cand_rest_days_sq_h": df["h_rest_days"].astype(float) ** 2,
        "cand_rest_days_sq_a": df["a_rest_days"].astype(float) ** 2,
    }


def _shot_quality_diff(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Shot-quality proxy: on-target share of shots (we have no true xG)."""
    h = (df["h_sot_pg"] / df["h_shots_pg"].replace(0, np.nan)).fillna(0.0)
    a = (df["a_sot_pg"] / df["a_shots_pg"].replace(0, np.nan)).fillna(0.0)
    return {"cand_shot_quality_diff": h - a}


def _momentum_differential(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Relative trajectory: an improving team vs a fading one."""
    return {"cand_momentum_diff": df["h_momentum"] - df["a_momentum"]}


def _venue_strength_asymmetry(df: pd.DataFrame) -> dict[str, pd.Series]:
    """How venue-dependent each side is, matched to this fixture's venue."""
    return {"cand_venue_asymmetry":
            (df["h_home_ppg"] - df["h_away_ppg"])
            + (df["a_away_ppg"] - df["a_home_ppg"])}


def _euro_congestion_delta(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Differential midweek-Europe congestion (rotation risk gap)."""
    return {"cand_euro_midweek_diff":
            df["h_euro_midweek"].astype(float) - df["a_euro_midweek"].astype(float)}


CANDIDATES: dict[str, dict] = {
    "rest_days_sq": {
        "hypothesis": ("Fatigue is nonlinear: 2 days of rest hurts far more "
                       "than a linear extrapolation from 5-vs-7 days implies. "
                       "Squaring rest days lets the Poisson regressions see "
                       "that curvature."),
        "enabled": False,
        "build": _rest_days_sq,
    },
    "shot_quality_diff": {
        "hypothesis": ("On-target share of shots is a shot-based stand-in for "
                       "chance quality (we label it shot-based, never true "
                       "xG). A team converting a higher share of shots "
                       "on target should outscore its raw shot volume."),
        "enabled": False,
        "build": _shot_quality_diff,
    },
    "momentum_differential": {
        "hypothesis": ("Relative trajectory carries signal beyond absolute "
                       "ratings: an improving side against a fading one is "
                       "worth more than the two ratings alone suggest."),
        "enabled": False,
        "build": _momentum_differential,
    },
    "venue_strength_asymmetry": {
        "hypothesis": ("Home advantage interacts with how venue-dependent each "
                       "team is. A strong home team hosting a poor traveler "
                       "is a bigger edge than venue splits already capture "
                       "independently."),
        "enabled": False,
        "build": _venue_strength_asymmetry,
    },
    "euro_congestion_delta": {
        "hypothesis": ("It is the congestion GAP that matters: a side that "
                       "played in Europe 3 days ago against a rested opponent "
                       "faces rotation risk the absolute midweek flags miss."),
        "enabled": False,
        "build": _euro_congestion_delta,
    },
}


def short_walkforward_poisson(df: pd.DataFrame, feature_cols: list[str],
                              n_splits: int = 2) -> float:
    """Mean log-loss of the Poisson model over a short time-respecting split."""
    X = df[feature_cols]
    y = df["result"].to_numpy()
    yh = df["home_goals"].to_numpy()
    ya = df["away_goals"].to_numpy()
    tscv = TimeSeriesSplit(n_splits=n_splits)
    losses = []
    for tr, te in tscv.split(X):
        w = fit.recency_weights(df["date"].iloc[tr])
        pm = fit.PoissonModel().fit(X.iloc[tr], yh[tr], ya[tr],
                                    sample_weight=w)
        probs = pm.predict_proba(X.iloc[te])
        losses.append(log_loss(y[te], probs, labels=LABELS))
    return float(np.mean(losses))


def ablate(league: str, dry_run: bool = False) -> dict:
    """Run baseline + per-candidate ablations. Returns measured results."""
    df, _ = build_features(league, mode="train")
    base_cols = [c for c in df.columns
                 if c.startswith(("h_", "a_")) or c == "h2h_edge"]
    if dry_run:
        log.info("ai_features_dry_run", league=league,
                 rows=len(df), base_cols=len(base_cols),
                 candidates=list(CANDIDATES))
        return {"league": league, "baseline": None, "candidates": {}}

    baseline = short_walkforward_poisson(df, base_cols)
    log.info("ai_features_baseline", league=league,
             logloss=round(baseline, 4))
    results: dict[str, dict] = {}
    for name, cand in CANDIDATES.items():
        cols = base_cols.copy()
        new_cols = cand["build"](df)
        tmp = df.copy()
        for col, series in new_cols.items():
            tmp[col] = series
            cols.append(col)
        ll = short_walkforward_poisson(tmp, cols)
        delta = ll - baseline
        if delta <= KEEP_THRESHOLD:
            verdict = "keep (recommend to human)"
        elif delta >= KILL_THRESHOLD:
            verdict = "kill"
        else:
            verdict = "needs-human-review"
        results[name] = {"delta_logloss": float(delta),
                         "logloss": float(ll),
                         "n_new_cols": len(new_cols),
                         "verdict": verdict}
        log.info("ai_features_candidate", league=league, name=name,
                 delta=round(delta, 5), verdict=verdict)
    return {"league": league, "baseline": float(baseline),
            "candidates": results}


def build_report(res: dict, run_date: date) -> str:
    league = res["league"]
    lines = [
        f"# AI feature ideation report — {league} — {run_date.isoformat()}",
        "",
        "> AI-generated. The agent proposes, the human vets: no candidate is",
        "> enabled by default, and nothing below changes the fitted models",
        "> until a human approves it.",
        "",
        "Protocol: short time-respecting walk-forward (2 splits) of the "
        "Poisson model only. Delta log-loss = candidate minus baseline "
        "(negative = better). All candidate inputs are shift(1)-lagged, so "
        "there is no leakage.",
        "",
    ]
    baseline = res.get("baseline")
    if baseline is None:
        lines.append("_Dry run: no ablations executed._")
    else:
        lines.append(f"Baseline Poisson log-loss (2 splits): {baseline:.4f}")
    lines += ["", "| candidate | hypothesis | delta log-loss | verdict |",
              "| --- | --- | --- | --- |"]
    for name, cand in CANDIDATES.items():
        r = res["candidates"].get(name, {})
        delta = r.get("delta_logloss")
        delta_s = f"{delta:+.5f}" if delta is not None else "n/a"
        verdict = r.get("verdict", "n/a")
        lines.append(f"| {name} | {cand['hypothesis']} | {delta_s} | "
                     f"{verdict} |")
    lines += ["",
              "## Flag state",
              "",
              "All candidates remain disabled by default:"]
    for name, cand in CANDIDATES.items():
        lines.append(f"- {name}: enabled = {cand['enabled']}")
    lines += ["", "---",
              "_Produced by etl.ai_features — proposals only, human vets._"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI feature ideation: propose candidates, ablate "
                    "time-respectingly, report verdicts.")
    parser.add_argument("--league", default="pl",
                        choices=settings.league_order,
                        help="league for the ablation (default: pl)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list candidates without running the ablation")
    args = parser.parse_args(argv)
    res = ablate(args.league, dry_run=args.dry_run)
    if args.dry_run:
        return 0
    report = build_report(res, date.today())
    path = (settings.data_dir /
            f"ai_feature_report_{date.today().isoformat()}.md")
    path.write_text(report)
    log.info("ai_feature_report_written", path=str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
