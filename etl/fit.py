"""Fit: per-league Poisson + ML models with recency weighting.

Two models per league, mirroring the EPL repo's parameterization:
  Statistical  PoissonRegressor on the lagged features (separate home-goals
               and away-goals regressions), converted to 1X2 probabilities
               through a 10x10 scoreline matrix.
  ML           XGBoost vs LightGBM on the same features; the better
               walk-forward log-loss wins per league and is reported as "ML".
  Ensemble     plain mean of the Poisson and ML probability vectors.

Every refresh refits on the full history with exponential recency weights
(half-life 180 days), so the model tracks form instead of going stale.
Walk-forward (TimeSeriesSplit) scores Poisson vs XGB vs LightGBM vs ensemble
vs a naive historical-rates baseline; all four are reported honestly on the
track-record page — if a model loses to the baseline, the numbers say so.

Saves data/params_{league}.json (params, fit date, data hash, walk-forward
table) and model artifacts under data/models/.

Usage: python -m etl.fit [--leagues ...] [--skip-walkforward]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone

import joblib
import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

from .config import settings
from .features import feature_logic_version
from .logging_setup import get_logger

log = get_logger(__name__)

LABELS = [0, 1, 2]  # away, draw, home
EPS = 1e-6


def recency_weights(dates: pd.Series) -> np.ndarray:
    """Exponential decay weights: half-life = settings.recency_half_life_days."""
    last = pd.to_datetime(dates).max()
    days_ago = (last - pd.to_datetime(dates)).dt.total_seconds() / 86400.0
    return 0.5 ** (days_ago / settings.recency_half_life_days)


def scoreline_to_1x2(lh: float, la: float) -> tuple[float, float, float]:
    """Bivariate Poisson scoreline matrix -> (p_away, p_draw, p_home)."""
    lh, la = max(float(lh), EPS), max(float(la), EPS)
    pa = pd_ = ph = 0.0
    for h in range(10):
        pmf_h = poisson.pmf(h, lh)
        for a in range(10):
            p = pmf_h * poisson.pmf(a, la)
            if h > a:
                ph += p
            elif h == a:
                pd_ += p
            else:
                pa += p
    tot = pa + pd_ + ph
    return pa / tot, pd_ / tot, ph / tot


class PoissonModel:
    """Poisson goal regressions -> 1X2, EPL-notebook parameterization."""

    def __init__(self) -> None:
        self.scaler = StandardScaler()
        self.reg_h = PoissonRegressor(alpha=0.1, max_iter=1000)
        self.reg_a = PoissonRegressor(alpha=0.1, max_iter=1000)

    def fit(self, X: pd.DataFrame, yh: np.ndarray, ya: np.ndarray,
            sample_weight: np.ndarray | None = None) -> "PoissonModel":
        Xs = self.scaler.fit_transform(X)
        self.reg_h.fit(Xs, yh, sample_weight=sample_weight)
        self.reg_a.fit(Xs, ya, sample_weight=sample_weight)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        Xs = self.scaler.transform(X)
        lh = self.reg_h.predict(Xs)
        la = self.reg_a.predict(Xs)
        out = np.zeros((len(X), 3))
        for i, (h, a) in enumerate(zip(lh, la)):
            out[i] = scoreline_to_1x2(h, a)
        return out

    def expected_goals(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        Xs = self.scaler.transform(X)
        return self.reg_h.predict(Xs), self.reg_a.predict(Xs)


def make_ml(kind: str):
    """Named ML configs. Small-data regime: strong regularization wins
    (chosen per league by walk-forward log-loss)."""
    if kind == "xgb_tiny":
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=100, max_depth=2, learning_rate=0.1,
                             min_child_weight=20, random_state=42, n_jobs=4,
                             eval_metric="mlogloss")
    if kind == "xgb_reg":
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                             min_child_weight=10, subsample=0.7,
                             colsample_bytree=0.7, reg_lambda=5.0,
                             random_state=42, n_jobs=4, eval_metric="mlogloss")
    if kind == "xgb_base":
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                             subsample=0.8, colsample_bytree=0.8,
                             reg_lambda=1.0, random_state=42, n_jobs=4,
                             eval_metric="mlogloss")
    if kind == "lgbm_a":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=100, num_leaves=15,
                              learning_rate=0.05, min_child_samples=50,
                              random_state=42, n_jobs=4, verbose=-1)
    from lightgbm import LGBMClassifier
    return LGBMClassifier(n_estimators=200, num_leaves=31,
                          learning_rate=0.03, min_child_samples=30,
                          random_state=42, n_jobs=4, verbose=-1)


ML_CONFIGS = ("xgb_tiny", "xgb_reg", "xgb_base", "lgbm_a", "lgbm_b")


def check_feature_version(league: str) -> None:
    meta_path = settings.data_dir / f"features_{league}.meta.json"
    meta = json.loads(meta_path.read_text())
    current = feature_logic_version()
    if meta["feature_logic_version"] != current:
        raise RuntimeError(
            f"features_{league}.csv was built by feature logic "
            f"{meta['feature_logic_version']}, current is {current}. "
            f"Re-run etl.features first.")


def walkforward(league: str, df: pd.DataFrame, feature_cols: list[str]) -> dict:
    X = df[feature_cols]
    y = df["result"].to_numpy()
    yh, ya = df["home_goals"].to_numpy(), df["away_goals"].to_numpy()
    tscv = TimeSeriesSplit(n_splits=settings.walkforward_splits)
    names = ["poisson", *ML_CONFIGS, "ensemble", "baseline"]
    agg: dict[str, dict[str, list[float]]] = {
        k: {"logloss": [], "accuracy": []} for k in names}
    for tr, te in tscv.split(X):
        Xtr, Xte = X.iloc[tr], X.iloc[te]
        yte = y[te]
        w = recency_weights(df["date"].iloc[tr])

        pm = PoissonModel().fit(Xtr, yh[tr], ya[tr], sample_weight=w)
        p_poisson = pm.predict_proba(Xte)

        p_ml = {}
        for kind in ML_CONFIGS:
            clf = make_ml(kind)
            clf.fit(Xtr, y[tr], sample_weight=w)
            p_ml[kind] = np.clip(clf.predict_proba(Xte), EPS, 1 - EPS)

        rates = np.bincount(y[tr], minlength=3) / len(tr)
        p_base = np.tile(rates, (len(te), 1))

        # Ensemble uses the best ML config on the train folds so far is
        # unknown; use xgb_tiny (the most regularized) as the stable pick.
        p_ens = (p_poisson + p_ml["xgb_tiny"]) / 2

        for name, probs in (("poisson", p_poisson),
                            *[(k, p_ml[k]) for k in ML_CONFIGS],
                            ("ensemble", p_ens), ("baseline", p_base)):
            agg[name]["logloss"].append(log_loss(yte, probs, labels=LABELS))
            agg[name]["accuracy"].append(accuracy_score(yte, probs.argmax(axis=1)))

    summary = {k: {m: float(np.mean(v)) for m, v in d.items()}
               for k, d in agg.items()}
    summary["always_home_accuracy"] = float(np.mean(y == 2))
    ml_best = min(ML_CONFIGS, key=lambda k: summary[k]["logloss"])
    summary["chosen_ml"] = ml_best
    log.info("walkforward", league=league, **{k: round(v["logloss"], 4)
                                             for k, v in summary.items()
                                             if isinstance(v, dict)})
    return summary


def fit_league(league: str, skip_walkforward: bool = False) -> dict:
    check_feature_version(league)
    feats_path = settings.data_dir / f"features_{league}.csv"
    df = pd.read_csv(feats_path, parse_dates=["date"])
    feature_cols = [c for c in df.columns
                    if c.startswith(("h_", "a_")) or c == "h2h_edge"]
    X = df[feature_cols]
    y = df["result"].to_numpy()

    wf = {} if skip_walkforward else walkforward(league, df, feature_cols)
    chosen_ml = wf.get("chosen_ml", "xgb_tiny") if wf else "xgb_tiny"

    w = recency_weights(df["date"])
    poisson_model = PoissonModel().fit(X, df["home_goals"].to_numpy(),
                                       df["away_goals"].to_numpy(),
                                       sample_weight=w)
    ml_model = make_ml(chosen_ml).fit(X, y, sample_weight=w)

    models_dir = settings.data_dir / "models"
    models_dir.mkdir(exist_ok=True)
    # Save components, not the wrapper: pickling a custom class defined in a
    # `python -m` entrypoint breaks on load (module is __main__ at save time).
    joblib.dump({"scaler": poisson_model.scaler,
                 "reg_h": poisson_model.reg_h,
                 "reg_a": poisson_model.reg_a},
                models_dir / f"{league}_poisson.joblib")
    joblib.dump(ml_model, models_dir / f"{league}_{chosen_ml}.joblib")
    joblib.dump(feature_cols, models_dir / f"{league}_features.joblib")

    meta = json.loads((settings.data_dir / f"features_{league}.meta.json").read_text())
    params = {
        "league": league,
        "model_version": f"v{date.today().isoformat()}",
        "fit_date": datetime.now(timezone.utc).isoformat(),
        "data_hash": meta["data_hash"],
        "feature_logic_version": meta["feature_logic_version"],
        "n_train_rows": len(df),
        "feature_cols": feature_cols,
        "chosen_ml": chosen_ml,
        "walkforward": wf,
    }
    (settings.data_dir / f"params_{league}.json").write_text(json.dumps(params, indent=1))
    log.info("fit_done", league=league, chosen_ml=chosen_ml, rows=len(df),
             version=params["model_version"])
    return params


def load_models(league: str):
    models_dir = settings.data_dir / "models"
    params = json.loads((settings.data_dir / f"params_{league}.json").read_text())
    parts = joblib.load(models_dir / f"{league}_poisson.joblib")
    poisson_model = PoissonModel()
    poisson_model.scaler, poisson_model.reg_h, poisson_model.reg_a = (
        parts["scaler"], parts["reg_h"], parts["reg_a"])
    ml_model = joblib.load(models_dir / f"{league}_{params['chosen_ml']}.joblib")
    feature_cols = joblib.load(models_dir / f"{league}_features.joblib")
    return poisson_model, ml_model, feature_cols, params


def predict_upcoming(league: str) -> pd.DataFrame:
    """1X2 probabilities (+ expected goals) for every scheduled fixture."""
    from .features import build_features  # deferred: needs fitted artifacts only
    poisson_model, ml_model, feature_cols, params = load_models(league)
    pred_df, _ = build_features(league, mode="predict")
    if pred_df.empty:
        return pred_df
    X = pred_df[feature_cols]
    p_poisson = poisson_model.predict_proba(X)
    p_ml = ml_model.predict_proba(X)
    p_ens = (p_poisson + p_ml) / 2
    xg_h, xg_a = poisson_model.expected_goals(X)
    out = pred_df[["fixture_id", "date", "home", "away"]].copy()
    out["p_away_poisson"], out["p_draw_poisson"], out["p_home_poisson"] = p_poisson.T
    out["p_away_ml"], out["p_draw_ml"], out["p_home_ml"] = p_ml.T
    out["p_away_ens"], out["p_draw_ens"], out["p_home_ens"] = p_ens.T
    out["xg_home"], out["xg_away"] = xg_h, xg_a
    out["model_version"] = params["model_version"]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit per-league Poisson + ML models.")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        choices=settings.league_order)
    parser.add_argument("--skip-walkforward", action="store_true")
    args = parser.parse_args(argv)
    for league in args.leagues:
        fit_league(league, skip_walkforward=args.skip_walkforward)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
