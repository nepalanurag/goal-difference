"""Permutation-assisted feature selection (thesis method, adapted).

Adapts Anurag's thesis permutation-assisted group lasso to the
Goal Difference ML features. The thesis method, per permutation, builds a
row-permuted knockoff copy of X, fits a group lasso on [X, X_knockoff] with
paired groups, and keeps original features that enter before their
knockoffs. A feature is finally selected when it is picked in >= cutoff
fraction of the permutations, with Jaccard similarity of the selected
sets across runs reported as the stability measure.

Adaptations for this project (multinomial 1X2 outcome, ~74 features in
11 natural groups, XGBoost as the ML workhorse):

* Groups are the natural feature families (form, venue, attack/defense,
  shots, discipline, h2h, rest/travel, european, absences, elo, odds)
  instead of correlation-clustered groups.
* Each group gets K row-permuted decoy copies (rows permuted independently
  per decoy). One xgb_tiny fit per permutation on [real + decoys].
* A group "beats its decoys" in a permutation when its total gain
  importance exceeds the best decoy copy's total gain (strict >, ties go
  to the decoy, the conservative choice).
* A group is selected when it beats its decoys in >= pi fraction of the
  B permutations. Selection frequency per group is reported.
* Stability: run the whole selection on two chronological halves of the
  data and report the Jaccard similarity of the two selected group sets
  (mirrors the thesis' calculate_subsequent_jaccard; two empty sets give
  1.0 by the same convention).

Output: data/pam_selection_{league}.json with selected groups, selection
frequencies per group, and the Jaccard stability.

Usage: python -m etl.pam_select [--leagues pl ...] [--K 5] [--B 20]
       [--pi 0.6] [--seed 42]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import settings
from .features import feature_columns
from .logging_setup import get_logger

log = get_logger(__name__)

# ----------------------------------------------------------------------------
# Feature groups. Columns are matched on the side-stripped name (h_/a_ prefix
# removed); h2h_edge / elo_diff / odds_* match on the full name.
# ----------------------------------------------------------------------------
GROUP_RULES: list[tuple[str, set[str]]] = [
    ("elo", {"elo", "elo_diff"}),
    ("odds", {"odds_p_home", "odds_p_draw", "odds_p_away", "odds_available"}),
    ("form", {"w5", "d5", "l5", "ppg_l5", "momentum"}),
    ("venue", {"ppg", "home_ppg", "away_ppg", "home_gf_pg", "home_ga_pg",
               "away_gf_pg", "away_ga_pg"}),
    ("attack_defense", {"gf_pg", "ga_pg", "gf_pg_l5", "ga_pg_l5",
                        "gf5", "ga5", "cs_rate", "fts_rate"}),
    ("shots", {"shots_pg", "shots_conc_pg", "sot_pg", "shot_diff_pg"}),
    ("discipline", {"fouls_pg", "cards_pg"}),
    ("h2h", {"h2h_edge"}),
    ("rest_travel", {"rest_days", "travel_km"}),
    ("european", {"euro_days_since", "euro_midweek", "euro_ppg", "euro_gd"}),
    ("absences", {"key_absences"}),
]

GROUP_ORDER = [name for name, _ in GROUP_RULES]

GROUP_LABELS = {
    "elo": "Elo ratings",
    "odds": "Market odds",
    "form": "Recent form",
    "venue": "Venue splits",
    "attack_defense": "Attack / defense",
    "shots": "Shot dominance",
    "discipline": "Discipline",
    "h2h": "Head-to-head edge",
    "rest_travel": "Rest and travel",
    "european": "European congestion",
    "absences": "Key absences",
}


def strip_side(col: str) -> str:
    """Remove the h_/a_ side prefix; h2h_edge has none and is untouched."""
    if col.startswith(("h_", "a_")):
        return col[2:]
    return col


def assign_group(col: str) -> str:
    """Map one feature column to its group. Raises KeyError if unmapped."""
    key = col if col in ("h2h_edge", "elo_diff") or col.startswith("odds_") else strip_side(col)
    for name, members in GROUP_RULES:
        if key in members:
            return name
    raise KeyError(f"no PAM group for feature column {col!r}")


def feature_groups(feature_cols: list[str]) -> dict[str, list[str]]:
    """Group name -> member columns, in GROUP_ORDER, members in input order."""
    groups: dict[str, list[str]] = {name: [] for name, _ in GROUP_RULES}
    for col in feature_cols:
        groups[assign_group(col)].append(col)
    return {name: cols for name, cols in groups.items() if cols}


# ----------------------------------------------------------------------------
# Decoy machinery
# ----------------------------------------------------------------------------
def decoy_copy(X: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """One row-permuted copy of X: same values per column, y-link broken."""
    return X[rng.permutation(X.shape[0])]


def group_beats_decoys(gains: dict[str, float], group_cols: list[str],
                       decoy_cols: list[list[str]]) -> bool:
    """True when the real group's total gain beats every decoy copy's.

    Strict > : a tie goes to the decoy (conservative, like the thesis
    counting only strictly-better original entries).
    """
    real = sum(gains.get(c, 0.0) for c in group_cols)
    best_decoy = max((sum(gains.get(c, 0.0) for c in dc) for dc in decoy_cols),
                     default=0.0)
    return real > best_decoy


def _fit_importance(X: pd.DataFrame, y: np.ndarray,
                    sample_weight: np.ndarray | None) -> dict[str, float]:
    from .fit import make_ml  # deferred: fit imports this module for wiring
    clf = make_ml("xgb_tiny")
    clf.fit(X, y, sample_weight=sample_weight)
    return dict(clf.get_booster().get_score(importance_type="gain"))


def selection_frequencies(df: pd.DataFrame, feature_cols: list[str],
                          groups: dict[str, list[str]],
                          K: int, B: int, seed: int) -> dict[str, float]:
    """Fraction of B permutations in which each group beats its K decoys."""
    X = df[feature_cols].to_numpy(dtype=np.float64)
    y = df["result"].to_numpy()
    w = df["sample_weight"].to_numpy() if "sample_weight" in df else None
    wins = {g: 0 for g in groups}
    for b in range(B):
        rng = np.random.default_rng(seed + b)
        parts = [X]
        decoy_slices: dict[str, list[list[str]]] = {g: [] for g in groups}
        names = list(feature_cols)
        for g, cols in groups.items():
            idx = [feature_cols.index(c) for c in cols]
            for k in range(K):
                dcols = [f"decoy::{g}::{k}::{c}" for c in cols]
                parts.append(decoy_copy(X[:, idx], rng))
                names.extend(dcols)
                decoy_slices[g].append(dcols)
        Xb = pd.DataFrame(np.hstack(parts), columns=names)
        gains = _fit_importance(Xb, y, w)
        for g, cols in groups.items():
            if group_beats_decoys(gains, cols, decoy_slices[g]):
                wins[g] += 1
    return {g: wins[g] / B for g in groups}


def select_groups(frequencies: dict[str, float], pi: float) -> list[str]:
    """Groups beating their decoys in >= pi fraction of permutations."""
    return [g for g in GROUP_ORDER if g in frequencies and frequencies[g] >= pi]


def jaccard(a: set[str] | list[str], b: set[str] | list[str]) -> float:
    """Jaccard similarity; two empty sets score 1.0 (thesis convention)."""
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------
def run_pam(df: pd.DataFrame, feature_cols: list[str], K: int = 5,
            B: int = 20, pi: float = 0.6, seed: int = 42,
            stability: bool = True) -> dict:
    """Full PAM selection; returns the JSON-serializable result dict."""
    groups = feature_groups(feature_cols)
    log.info("pam_start", n_rows=len(df), n_groups=len(groups), K=K, B=B, pi=pi)

    freqs = selection_frequencies(df, feature_cols, groups, K, B, seed)
    selected = select_groups(freqs, pi)

    stab, halves = None, None
    if stability:
        mid = len(df) // 2
        halves = {}
        for name, part in (("first", df.iloc[:mid]), ("second", df.iloc[mid:])):
            f = selection_frequencies(part, feature_cols, groups, K, B, seed + 1000)
            halves[name] = select_groups(f, pi)
        stab = jaccard(halves["first"], halves["second"])
        log.info("pam_stability", jaccard=round(stab, 3), **halves)

    selected_features = [c for g in selected for c in groups[g]]
    log.info("pam_done", selected_groups=selected,
             n_features=len(selected_features),
             freqs={g: round(f, 2) for g, f in freqs.items()})
    return {
        "method": ("permutation-assisted group selection; thesis method "
                   "adapted: K row-permuted decoy copies per group, "
                   "xgb_tiny gain importance, pi threshold"),
        "K": K, "B": B, "pi": pi, "seed": seed,
        "n_rows": len(df),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "groups": groups,
        "selection_frequency": freqs,
        "selected_groups": selected,
        "selected_features": selected_features,
        "jaccard_stability": stab,
        "stability_halves": halves,
        "ml_model": "xgb_tiny",
    }


def load_pam_selection(league: str, feature_cols: list[str]) -> dict | None:
    """Load a PAM result if it exists and is usable; else None (warn)."""
    path = settings.data_dir / f"pam_selection_{league}.json"
    if not path.exists():
        log.info("pam_missing_fallback_full", league=league)
        return None
    try:
        pam = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("pam_unreadable_fallback_full", league=league, error=str(e))
        return None
    sel = [c for c in pam.get("selected_features", []) if c in feature_cols]
    if not sel:
        log.warning("pam_empty_fallback_full", league=league)
        return None
    pam["selected_features"] = sel
    pam["selected_groups"] = [g for g in pam.get("selected_groups", [])
                              if g in pam.get("groups", {})]
    return pam


def fit_pam_league(league: str, K: int = 5, B: int = 20, pi: float = 0.6,
                   seed: int = 42) -> dict:
    feats_path = settings.data_dir / f"features_{league}.csv"
    df = pd.read_csv(feats_path, parse_dates=["date"])
    feature_cols = feature_columns(df)
    # Recency weights match fit.py so selection sees the same emphasis.
    from .fit import recency_weights
    df = df.copy()
    df["sample_weight"] = recency_weights(df["date"])
    result = run_pam(df, feature_cols, K=K, B=B, pi=pi, seed=seed)
    result["league"] = league
    out = settings.data_dir / f"pam_selection_{league}.json"
    out.write_text(json.dumps(result, indent=1))
    log.info("pam_written", league=league, path=str(out))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Permutation-assisted feature selection per league.")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        choices=settings.league_order)
    parser.add_argument("--K", type=int, default=5)
    parser.add_argument("--B", type=int, default=20)
    parser.add_argument("--pi", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    for league in args.leagues:
        fit_pam_league(league, K=args.K, B=args.B, pi=args.pi, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
