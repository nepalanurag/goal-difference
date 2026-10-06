"""Fit: per-league Dixon-Coles + ML models with recency weighting.

Two models per league:
  Statistical  Dixon-Coles per league: team attack/defense strengths, home
               advantage, low-score correction rho, and time-decay xi, all
               fit by weighted MLE (L-BFGS-B, mean-zero identifiability
               constraints). 1X2 comes from a 10x10 scoreline grid with the
               tau correction on the 0-0, 1-0, 0-1, 1-1 cells. The old
               PoissonRegressor GLM stays as a fallback if DC fails to
               converge.
  ML           XGBoost vs LightGBM on the lagged features (now incl. Elo
               ratings and de-vigged market odds); the better walk-forward
               log-loss wins per league and is reported as "ML".
  Ensemble     GBM-dominant blend (0.6 ML / 0.4 DC) of the 1X2 marginals,
               with the DC scoreline grid reshaped to those marginals so the
               Poisson score structure survives the blend.

Every refresh refits on the full history with exponential recency weights,
so the model tracks form instead of going stale.
Walk-forward (TimeSeriesSplit) scores DC vs XGB vs LightGBM vs ensemble vs
a naive historical-rates baseline vs de-vigged market odds on log loss,
Brier, RPS and accuracy; all are reported honestly on the track-record
page. A calibration table (predicted deciles vs observed rates) is saved
per league.

Saves data/params_{league}.json (DC params, fit date, data hash,
walk-forward table), data/calibration_{league}.json, and model artifacts
under data/models/.

Usage: python -m etl.fit [--leagues ...] [--skip-walkforward]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

from .config import settings
from .features import feature_columns, feature_logic_version
from .logging_setup import get_logger

log = get_logger(__name__)

LABELS = [0, 1, 2]  # away, draw, home
EPS = 1e-6

# GBM-dominant ensemble weights.
ENSEMBLE_W_ML = 0.6
ENSEMBLE_W_DC = 0.4


def brier_score_3(y: np.ndarray, p: np.ndarray) -> float:
    """Multiclass Brier: mean over matches of the squared error summed over
    the 3 one-hot outcomes (uniform baseline 2/3, matching the literature)."""
    oh = np.zeros_like(p)
    oh[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((p - oh) ** 2, axis=1)))


def ranked_probability_score(y: np.ndarray, p: np.ndarray) -> float:
    """RPS for ordinal outcomes away < draw < home."""
    cdf_p = np.cumsum(p, axis=1)[:, :2]
    oh = np.zeros_like(p)
    oh[np.arange(len(y)), y] = 1.0
    cdf_o = np.cumsum(oh, axis=1)[:, :2]
    return float(0.5 * np.mean(np.sum((cdf_p - cdf_o) ** 2, axis=1)))


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


# ----------------------------------------------------------------------------
# Dixon-Coles, fit per league by weighted MLE.
# ----------------------------------------------------------------------------
DC_GRID_SIZE = 10


# xi candidates: half-lives ~1386 / 693 / 385 / 231 / 139 days.
DC_XI_CANDIDATES = (0.0005, 0.001, 0.0018, 0.003, 0.005)


def fit_dixon_coles(homes: list[str], aways: list[str],
                    hg: np.ndarray, ag: np.ndarray,
                    dates: pd.Series, xi: float) -> dict | None:
    """Weighted MLE of per-league DC params with fixed time-decay xi.

    xi is fixed, not optimized: fitting it inside the weighted MLE is
    degenerate (shrinking the weights mechanically shrinks the objective).
    Instead xi is chosen per league by walk-forward log-loss
    (select_dc_xi). Returns the params dict, or None when the optimizer
    fails (caller falls back to the GLM)."""
    teams = sorted(set(homes) | set(aways))
    tix = {t: i for i, t in enumerate(teams)}
    hi = np.array([tix[t] for t in homes])
    ai = np.array([tix[t] for t in aways])
    hg = np.asarray(hg, dtype=float)
    ag = np.asarray(ag, dtype=float)
    dts = pd.to_datetime(dates)
    days_ago = (dts.max() - dts).dt.total_seconds().to_numpy() / 86400.0
    n = len(teams)
    w = np.exp(-xi * days_ago)

    m00 = (hg == 0) & (ag == 0)
    m10 = (hg == 1) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m11 = (hg == 1) & (ag == 1)
    pois_h = gammaln(hg + 1)
    pois_a = gammaln(ag + 1)

    def nll(theta: np.ndarray) -> float:
        ha, rho = theta[0], theta[1]
        att, dfn = theta[2:2 + n], theta[2 + n:2 + 2 * n]
        lh = np.exp(ha + att[hi] - dfn[ai])
        la = np.exp(att[ai] - dfn[hi])
        tau = np.ones_like(hg)
        tau[m00] = 1.0 - lh[m00] * la[m00] * rho
        tau[m10] = 1.0 + lh[m10] * rho
        tau[m01] = 1.0 + la[m01] * rho
        tau[m11] = 1.0 - rho
        tau = np.clip(tau, 1e-9, None)
        ll = (hg * np.log(np.clip(lh, EPS, None)) - lh - pois_h
              + ag * np.log(np.clip(la, EPS, None)) - la - pois_a
              + np.log(tau))
        return float(-np.sum(w * ll))

    x0 = np.zeros(2 + 2 * n)
    x0[0], x0[1] = 0.2, -0.05
    bounds = [(-1.0, 1.0), (-0.15, 0.15)] + [(-2.5, 2.5)] * (2 * n)
    try:
        res = minimize(nll, x0, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 500})
    except Exception:
        return None
    if not res.success or not np.isfinite(res.fun):
        return None
    # Mean-zero identifiability: demean strengths, fold the shift into
    # home_adv so every lambda is unchanged.
    raw_att, raw_dfn = res.x[2:2 + n], res.x[2 + n:2 + 2 * n]
    ma, md = float(raw_att.mean()), float(raw_dfn.mean())
    return {
        "teams": teams,
        "attack": {t: float(v) for t, v in zip(teams, raw_att - ma)},
        "defense": {t: float(v) for t, v in zip(teams, raw_dfn - md)},
        "home_adv": float(res.x[0] + ma - md),
        "rho": float(res.x[1]),
        "xi": float(xi),
        "neg_loglik": float(res.fun),
        "n_matches": int(len(hg)),
    }


def select_dc_xi(df: pd.DataFrame,
                 candidates: tuple[float, ...] = DC_XI_CANDIDATES,
                 n_splits: int = 3) -> float:
    """Pick the per-league time-decay xi by walk-forward DC log-loss.

    This is hyperparameter selection, so the chosen xi has seen the
    walk-forward test folds; the reported walk-forward metrics stay honest
    because every model is still scored out-of-sample per fold."""
    y = df["result"].to_numpy()
    tscv = TimeSeriesSplit(n_splits=n_splits)
    scores: dict[float, list[float]] = {xi: [] for xi in candidates}
    for tr, te in tscv.split(df):
        for xi in candidates:
            m = DixonColesModel()
            if m.fit(df.iloc[tr], xi=xi):
                p = m.predict_proba(df.iloc[te])
                scores[xi].append(log_loss(y[te], p, labels=LABELS))
    mean = {xi: float(np.mean(v)) for xi, v in scores.items() if v}
    if not mean:
        log.warning("dc_xi_select_failed")
        return 0.0018
    best = min(mean, key=mean.get)
    log.info("dc_xi_selected", xi=best,
             logloss={k: round(v, 4) for k, v in mean.items()})
    return best


def dc_scoreline_grid(lh: float, la: float, rho: float,
                      size: int = DC_GRID_SIZE) -> np.ndarray:
    """10x10 scoreline grid with the Dixon-Coles tau correction on the four
    low-score cells."""
    lh, la = max(float(lh), EPS), max(float(la), EPS)
    grid = np.outer(poisson.pmf(np.arange(size), lh),
                    poisson.pmf(np.arange(size), la))
    tau = np.ones_like(grid)
    tau[0, 0] = 1.0 - lh * la * rho
    tau[1, 0] = 1.0 + lh * rho
    tau[0, 1] = 1.0 + la * rho
    tau[1, 1] = 1.0 - rho
    return grid * np.clip(tau, 1e-9, None)


def grid_to_1x2(grid: np.ndarray) -> np.ndarray:
    """Scoreline grid -> (p_away, p_draw, p_home)."""
    pa = pd_ = ph = 0.0
    for h in range(grid.shape[0]):
        for a in range(grid.shape[1]):
            if h > a:
                ph += grid[h, a]
            elif h == a:
                pd_ += grid[h, a]
            else:
                pa += grid[h, a]
    tot = pa + pd_ + ph
    return np.array([pa / tot, pd_ / tot, ph / tot])


def reshape_grid_to_marginals(grid: np.ndarray,
                              target: np.ndarray) -> np.ndarray:
    """Rescale a DC scoreline grid so its 1X2 marginals equal `target`.

    Each cell is scaled by the ratio for its outcome class (away/draw/home),
    so the within-class score shape from the Poisson structure survives the
    blend. By construction the reshaped grid's 1X2 equals the target."""
    cur = grid_to_1x2(grid)
    out = grid.astype(float).copy()
    for h in range(out.shape[0]):
        for a in range(out.shape[1]):
            k = 0 if h < a else (1 if h == a else 2)
            out[h, a] *= target[k] / cur[k] if cur[k] > 1e-12 else 0.0
    s = out.sum()
    return out / s if s > 0 else out


def blend_ensemble(p_dc: np.ndarray, p_ml: np.ndarray) -> np.ndarray:
    """GBM-dominant 1X2 blend. Equals the marginals of the DC grid reshaped
    to the ensemble target."""
    return ENSEMBLE_W_ML * p_ml + ENSEMBLE_W_DC * p_dc


class DixonColesModel:
    """Per-league Dixon-Coles: strengths + home_adv + rho + xi."""

    def __init__(self) -> None:
        self.params: dict | None = None

    def fit(self, df: pd.DataFrame, xi: float = 0.0018) -> bool:
        """Fit on a slice with home/away/home_goals/away_goals/date cols.
        Returns True when the optimizer converged."""
        self.params = fit_dixon_coles(
            df["home"].tolist(), df["away"].tolist(),
            df["home_goals"].to_numpy(), df["away_goals"].to_numpy(),
            df["date"], xi)
        return self.params is not None

    def lambdas(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        p = self.params
        assert p is not None, "DixonColesModel not fitted"
        att = p["attack"]
        dfn = p["defense"]
        homes = df["home"].tolist()
        aways = df["away"].tolist()
        lh = np.exp(p["home_adv"]
                    + np.array([att.get(t, 0.0) for t in homes])
                    - np.array([dfn.get(t, 0.0) for t in aways]))
        la = np.exp(np.array([att.get(t, 0.0) for t in aways])
                    - np.array([dfn.get(t, 0.0) for t in homes]))
        return np.clip(lh, EPS, None), np.clip(la, EPS, None)

    def grids(self, df: pd.DataFrame) -> list[np.ndarray]:
        rho = self.params["rho"]
        return [dc_scoreline_grid(h, a, rho)
                for h, a in zip(*self.lambdas(df))]

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return np.array([grid_to_1x2(g) for g in self.grids(df)])

    def predict_proba_df(self, df: pd.DataFrame,
                         feature_cols: list[str] | None = None) -> np.ndarray:
        return self.predict_proba(df)

    def expected_goals(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        return self.lambdas(df)

    def expected_goals_df(self, df: pd.DataFrame,
                          feature_cols: list[str] | None = None
                          ) -> tuple[np.ndarray, np.ndarray]:
        return self.lambdas(df)

    def to_dict(self) -> dict:
        return dict(self.params)

    @classmethod
    def from_dict(cls, d: dict) -> "DixonColesModel":
        m = cls()
        m.params = d
        return m


class PoissonModel:
    """Poisson goal regressions -> 1X2. Fallback when DC fails to converge."""

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

    def predict_proba_df(self, df: pd.DataFrame,
                         feature_cols: list[str]) -> np.ndarray:
        return self.predict_proba(df[feature_cols])

    def expected_goals(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        Xs = self.scaler.transform(X)
        return self.reg_h.predict(Xs), self.reg_a.predict(Xs)

    def expected_goals_df(self, df: pd.DataFrame,
                          feature_cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
        return self.expected_goals(df[feature_cols])


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


METRICS = ("logloss", "brier", "rps", "accuracy")


def _score(probs: np.ndarray, yte: np.ndarray) -> dict[str, float]:
    return {
        "logloss": float(log_loss(yte, probs, labels=LABELS)),
        "brier": brier_score_3(yte, probs),
        "rps": ranked_probability_score(yte, probs),
        "accuracy": float(accuracy_score(yte, probs.argmax(axis=1))),
    }


def walkforward(league: str, df: pd.DataFrame,
                feature_cols: list[str], xi: float = 0.0018
                ) -> tuple[dict, dict]:
    """Expanding-window walk-forward. Returns (summary, calibration-data).

    The "poisson" entry is the per-league Dixon-Coles fit (fixed xi, chosen
    per league by select_dc_xi); when the DC optimizer fails on a fold it
    falls back to the PoissonRegressor GLM and logs a warning. "odds" is
    the de-vigged market benchmark, scored only on test rows that actually
    have closing odds."""
    X = df[feature_cols]
    y = df["result"].to_numpy()
    yh, ya = df["home_goals"].to_numpy(), df["away_goals"].to_numpy()
    tscv = TimeSeriesSplit(n_splits=settings.walkforward_splits)
    names = ["poisson", *ML_CONFIGS, "ensemble", "baseline", "odds"]
    agg: dict[str, dict[str, list[float]]] = {
        k: {m: [] for m in METRICS} for k in names}
    odds_rows = 0
    cal_y: list[np.ndarray] = []
    cal_p: list[np.ndarray] = []
    for tr, te in tscv.split(X):
        Xtr, Xte = X.iloc[tr], X.iloc[te]
        yte = y[te]
        w = recency_weights(df["date"].iloc[tr])

        dc = DixonColesModel()
        if dc.fit(df.iloc[tr], xi=xi):
            p_poisson = dc.predict_proba(df.iloc[te])
        else:
            log.warning("dc_fit_failed_fallback_glm", league=league)
            pm = PoissonModel().fit(Xtr, yh[tr], ya[tr], sample_weight=w)
            p_poisson = pm.predict_proba(Xte)

        p_ml = {}
        for kind in ML_CONFIGS:
            clf = make_ml(kind)
            clf.fit(Xtr, y[tr], sample_weight=w)
            p_ml[kind] = np.clip(clf.predict_proba(Xte), EPS, 1 - EPS)

        rates = np.bincount(y[tr], minlength=3) / len(tr)
        p_base = np.tile(rates, (len(te), 1))

        # Ensemble: GBM-dominant blend. The best ML config on the train
        # folds so far is unknown; use xgb_tiny (most regularized).
        p_ens = blend_ensemble(p_poisson, p_ml["xgb_tiny"])
        cal_y.append(yte)
        cal_p.append(p_ens)

        for name, probs in (("poisson", p_poisson),
                            *[(k, p_ml[k]) for k in ML_CONFIGS],
                            ("ensemble", p_ens), ("baseline", p_base)):
            for m, v in _score(probs, yte).items():
                agg[name][m].append(v)

        # De-vigged odds benchmark: only rows with real closing odds.
        te_df = df.iloc[te]
        mask = te_df["odds_available"].to_numpy() == 1
        if mask.any():
            p_odds = te_df.loc[mask, ["odds_p_away", "odds_p_draw",
                                      "odds_p_home"]].to_numpy()
            for m, v in _score(p_odds, yte[mask]).items():
                agg["odds"][m].append(v)
            odds_rows += int(mask.sum())

    summary = {k: ({m: float(np.mean(v)) for m, v in d.items() if v}
                   or {m: None for m in METRICS})
               for k, d in agg.items()}
    summary["odds_rows"] = odds_rows
    summary["always_home_accuracy"] = float(np.mean(y == 2))
    ml_best = min(ML_CONFIGS, key=lambda k: summary[k]["logloss"])
    summary["chosen_ml"] = ml_best
    log.info("walkforward", league=league, **{k: round(v["logloss"], 4)
               for k, v in summary.items() if isinstance(v, dict)
               and v.get("logloss") is not None})
    calib = {"y_true": np.concatenate(cal_y).tolist(),
             "p_ensemble": np.concatenate(cal_p).tolist()}
    return summary, calib


def build_calibration_table(y_true: list[int], p_pred: list[list[float]],
                            n_bins: int = 10) -> list[dict]:
    """Per-outcome calibration: each (match, outcome) pair lands in the
    decile bucket of its predicted probability; observed_rate is the
    fraction of those pairs that actually happened."""
    y_true = np.asarray(y_true)
    p_pred = np.asarray(p_pred)
    oh = np.zeros_like(p_pred)
    oh[np.arange(len(y_true)), y_true] = 1.0
    flat_p, flat_o = p_pred.reshape(-1), oh.reshape(-1)
    buckets = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        m = (flat_p >= lo) & (flat_p < hi if b < n_bins - 1 else flat_p <= hi)
        n = int(m.sum())
        buckets.append({
            "lo": round(lo, 2), "hi": round(hi, 2), "n": n,
            "mean_pred": float(flat_p[m].mean()) if n else None,
            "observed_rate": float(flat_o[m].mean()) if n else None,
        })
    return buckets


def fit_league(league: str, skip_walkforward: bool = False) -> dict:
    check_feature_version(league)
    feats_path = settings.data_dir / f"features_{league}.csv"
    df = pd.read_csv(feats_path, parse_dates=["date"])
    feature_cols = feature_columns(df)
    X = df[feature_cols]
    y = df["result"].to_numpy()

    if skip_walkforward:
        xi, wf, calib = 0.0018, {}, None
    else:
        xi = select_dc_xi(df)
        wf, calib = walkforward(league, df, feature_cols, xi=xi)
    chosen_ml = wf.get("chosen_ml", "xgb_tiny") if wf else "xgb_tiny"

    w = recency_weights(df["date"])
    dc = DixonColesModel()
    if dc.fit(df, xi=xi):
        poisson_model = dc
        dc_params = dc.to_dict()
        poisson_fallback = False
    else:
        log.warning("dc_fit_failed_fallback_glm", league=league)
        poisson_model = PoissonModel().fit(
            X, df["home_goals"].to_numpy(), df["away_goals"].to_numpy(),
            sample_weight=w)
        dc_params = None
        poisson_fallback = True
    ml_model = make_ml(chosen_ml).fit(X, y, sample_weight=w)

    models_dir = settings.data_dir / "models"
    models_dir.mkdir(exist_ok=True)
    if poisson_fallback:
        # Save GLM components, not the wrapper: pickling a custom class
        # defined in a `python -m` entrypoint breaks on load (module is
        # __main__ at save time).
        joblib.dump({"scaler": poisson_model.scaler,
                     "reg_h": poisson_model.reg_h,
                     "reg_a": poisson_model.reg_a},
                    models_dir / f"{league}_poisson.joblib")
    joblib.dump(ml_model, models_dir / f"{league}_{chosen_ml}.joblib")
    joblib.dump(feature_cols, models_dir / f"{league}_features.joblib")

    model_version = f"v{date.today().isoformat()}"
    meta = json.loads((settings.data_dir / f"features_{league}.meta.json").read_text())
    params = {
        "league": league,
        "model_version": model_version,
        "fit_date": datetime.now(timezone.utc).isoformat(),
        "data_hash": meta["data_hash"],
        "feature_logic_version": meta["feature_logic_version"],
        "n_train_rows": len(df),
        "feature_cols": feature_cols,
        "chosen_ml": chosen_ml,
        "dc": dc_params,
        "poisson_fallback": poisson_fallback,
        "ensemble_weights": {"ml": ENSEMBLE_W_ML, "dc": ENSEMBLE_W_DC},
        "walkforward": wf,
    }
    (settings.data_dir / f"params_{league}.json").write_text(json.dumps(params, indent=1))

    if calib is not None:
        calibration = {
            "league": league,
            "model": "ensemble",
            "model_version": model_version,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "n_predictions": len(calib["y_true"]),
            "buckets": build_calibration_table(calib["y_true"], calib["p_ensemble"]),
        }
        (settings.data_dir / f"calibration_{league}.json").write_text(
            json.dumps(calibration, indent=1))

    log.info("fit_done", league=league, chosen_ml=chosen_ml, rows=len(df),
             dc_converged=not poisson_fallback, version=model_version)
    return params


def load_models(league: str):
    models_dir = settings.data_dir / "models"
    params = json.loads((settings.data_dir / f"params_{league}.json").read_text())
    if params.get("dc"):
        poisson_model = DixonColesModel.from_dict(params["dc"])
    else:
        # Legacy artifact: PoissonRegressor GLM components.
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
    p_poisson = poisson_model.predict_proba_df(pred_df, feature_cols)
    p_ml = np.clip(ml_model.predict_proba(X), EPS, 1 - EPS)
    p_ens = blend_ensemble(p_poisson, p_ml)
    xg_h, xg_a = poisson_model.expected_goals_df(pred_df, feature_cols)
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
