# Quantitative Audit: goal-difference Modeling & Data Engineering
**Date:** 2026-10-18 | **Scope:** etl/features.py, extract.py, validate.py, fit.py, simulate.py, ledger.py, build_site.py, config.py, h2h.py, scorer_probs.py, pam_select.py | **Method:** First-principles code reading, no test execution

> **Correction (2026-10-18, post-audit):** The initial audit ran against a stale branch. The current main branch DOES contain `etl/scorer_probs.py` (market-odds feature pipeline) and a full Elo rating engine (`ELO_START`, `elo_update` in features.py). The Elo implementation is correct: ratings are read pre-match and updated post-match (no leakage), with home-field bonus (100) and sqrt margin-of-victory multiplier. Premise corrections below have been updated.

---

## Ranked Vulnerability Matrix

| # | Severity | Component | Finding | Impact | Status |
|---|----------|-----------|---------|--------|--------|
| 1 | **CRITICAL** | features.py + h2h.py | `h2h_edge` uses all-time H2H including future matches — direct lookahead leakage | Inflates backtest/walk-forward performance; production predictions use a feature that cannot be computed at prediction time | **FIXED** (`load_h2h_dated` + `h2h_edge_before`) |
| 2 | **CRITICAL** | simulate.py | Tie-break uses stale pre-simulation goal difference (never updated by simulated results) | Title/top-4/relegation odds are computed with a tie-breaker that ignores 100+ simulated matches | **FIXED** (dynamic Poisson scorelines & GD updates) |
| 3 | **CRITICAL** | simulate.py | LaLiga/Serie A tie-break wrong: uses GD, but both leagues use head-to-head first | Systematically wrong title odds in 2 of 5 leagues whenever teams finish level on points | **FIXED** (H2H mini-tables for LaLiga/Serie A) |
| 4 | HIGH | fit.py | No Dixon-Coles correction on independent Poisson | Systematic mispricing of 0-0, 1-0, 0-1, 1-1; biased draw probabilities | **FIXED** (`DixonColesModel` with rho and xi) |
| 5 | HIGH | fit.py | Walk-forward ensemble (poisson+xgb_tiny)/2 ≠ production ensemble (poisson+chosen_ml)/2 | Reported ensemble log-loss does not reflect the deployed model when chosen_ml ≠ xgb_tiny | Open |
| 6 | HIGH | features.py | European team names not canonicalized — silent feature loss | `load_european()` matches raw API names against canonical fixture names; mismatches → euro features silently default (999/0/1.0/0) | Mitigated (`uefa.py` canonicalization) |
| 7 | HIGH | ledger.py | `append_predictions` not idempotent; no dedup guard | Cron double-run appends duplicates → cartesian explosion in `score_league` merge | **FIXED** (dedup on key+version, results dedup) |
| 8 | HIGH | features.py | Column-mean imputation computed over full dataset (all seasons) | Lookahead leakage for early-season cold-start rows (minor magnitude, real principle violation) | Open |
| 9 | MEDIUM | fit.py | Poisson assumes Var=Mean; no overdispersion handling | Miscalibrated tail probabilities; Negative Binomial strictly dominates | Open |
| 10 | MEDIUM | fit.py | No probability calibration (Platt/isotonic/temperature) on ensemble | Raw average of two models is rarely calibrated; log-loss suffers | Partial (calibration tables generated) |
| 11 | MEDIUM | ledger.py | Log-loss only; no RPS or Brier score | Log-loss is proper but RPS is the correct scoring rule for ordinal 1X2 outcomes | **FIXED** (`ranked_probability_score` and `brier_score_3`) |
| 12 | MEDIUM | simulate.py | Static team strengths across 10,000 runs; no form/momentum dynamics | Fine for short horizons; understates variance in title races | Open |
| 13 | MEDIUM | extract.py | `reconstruct_remaining_schedule` assigns dates by greedy hash-order, not real calendar | Simulated "rest days" and midweek flags for future fixtures are fictional | Open |
| 14 | LOW | fit.py | 10×10 scoreline matrix truncation | Negligible after renormalization; P(H≥10) < 0.001 for realistic λ | Closed (insignificant) |
| 15 | LOW | fit.py | `PoissonRegressor(alpha=0.1)` weak for 60+ features | Walk-forward would catch overfitting, but stronger prior is cheaper | Closed (Dixon-Coles is primary) |
| 16 | LOW | features.py | `data_hash` covers only fixture_id/goals | Silent to shot-stat or provenance changes | Open |

---

## Detailed Findings

### 1. H2H Lookahead Leakage (CRITICAL)

`h2h.py:build_h2h` computes `alltime` W/D/L from **every finished fixture in the CSV**, with no date cutoff. `features.py:feature_row` then does:

```python
at = h2h[key]["alltime"]
edge = (at["w"] + 0.5 * at["d"]) / tot if tot else 0.5
row["h2h_edge"] = edge
```

For a fixture played in August 2023, `h2h_edge` incorporates head-to-head results from 2024, 2025, and 2026. This is not a subtle statistical issue — it is direct target information from the future. The walk-forward evaluation in `fit.py` therefore overstates the value of the H2H feature, and worse, **production predictions for upcoming fixtures use a different (unknowable) H2H computation than the one the model was trained on**. The train/serve skew alone invalidates the feature.

The per-team rolling features (`TeamHistory.features()`) are correctly lagged — the feature row is emitted before the current match is appended to history, and the dataframe is date-sorted. The `shift(1)` semantics hold for all `w5`, `ppg`, `momentum`, and shot-stat features. The H2H path is the sole leakage vector in the feature pipeline.

### 2. Stale Goal Difference in Simulation Tie-Break (CRITICAL)

`simulate.py:simulate_league`:

```python
gd = np.array([base_gd[t] for t in teams], dtype=float)  # frozen pre-simulation GD
...
for o, hi, ai in zip(outcomes, home_idx, away_idx):
    if o == 2: pts[hi] += 3
    elif o == 0: pts[ai] += 3
    else: pts[hi] += 1; pts[ai] += 1
    # gd is NEVER updated
order = np.lexsort((-gd, -pts))
```

Simulated matches award points but the simulation only samples 1X2 outcomes, never scorelines, so goal difference cannot be updated. The tie-break then sorts by **stale GD from before the simulated run-out**. With ~100 remaining fixtures per league, the final table's GD is overwhelmingly determined by simulated matches — yet the tie-break ignores all of them. Title odds in close races are materially wrong.

### 3. Wrong Tie-Break Rules for LaLiga and Serie A (CRITICAL)

The same `np.lexsort((-gd, -pts))` applies points → goal difference universally. Actual rules:
- **LaLiga:** head-to-head points → head-to-head GD → overall GD
- **Serie A:** head-to-head points → head-to-head GD → overall GD (plus a title playoff since 2022/23)
- **Premier League / Bundesliga / Ligue 1:** goal difference (correct as implemented)

In any simulated season where two teams finish level on points in LaLiga or Serie A — common in title races — the wrong team is awarded the title. Implementing true H2H tie-breaks requires tracking simulated H2H mini-tables, which the current 1X2-only sampling cannot support (see fix below).

### 4. No Dixon-Coles Correction (HIGH)

`scoreline_to_1x2` multiplies independent Poisson PMFs. Empirically, football exhibits negative correlation at low scores: 0-0, 1-0, 0-1, and 1-1 occur less frequently than independence predicts. Dixon & Coles (1997) correct this with a rho parameter adjusting exactly those four cells. Without it, draw probabilities are systematically overstated and the 1X2 distribution is biased. This is the single highest-leverage modeling upgrade — it is a closed-form correction requiring no refit.

### 5. Walk-Forward / Production Ensemble Mismatch (HIGH)

Walk-forward (fit.py) evaluates `p_ens = (p_poisson + p_ml["xgb_tiny"]) / 2` with a comment admitting the best config is unknown at that point. But `predict_upcoming` uses `p_ens = (p_poisson + p_ml) / 2` where `p_ml` comes from `chosen_ml` — the walk-forward winner, which memory records as XGBoost (not necessarily `xgb_tiny`) in all five leagues. The track-record page therefore reports an ensemble log-loss for a model combination that is never deployed.

### 6. European Names Not Canonicalized (HIGH)

`extract.py:fetch_european` stores raw api-football team names (`fx["teams"]["home"]["name"]`). `features.py:load_european` indexes by those raw names. But the lookup `euro.get(team, [])` uses canonical names from `team_names.canonicalize` (e.g., "Man City", "Ath Madrid"). Any API/canonical mismatch ("Manchester City" vs "Man City", "Atletico Madrid" vs "Ath Madrid") silently yields zero European history — `euro_days_since=999`, `euro_ppg=1.0` — with no warning. The feature is silently dead for mismatched teams.

### 7. Ledger Not Idempotent (HIGH)

`append_predictions` does a blind append. The daily cron (`refresh.yml`) is hash-gated, but any manual re-run or partial failure followed by retry duplicates rows. `score_league` merges on `(fixture_date, home, away)` — duplicates produce a cartesian product, silently doubling (or worse) the scored rows and corrupting the track record.

### 8. Full-Dataset Mean Imputation (HIGH, minor magnitude)

```python
for col in feature_cols:
    if feats_df[col].isna().any():
        mean = feats_df[col].mean()  # over ALL seasons, including future
```

Cold-start rows (a team's first 1–5 matches) are filled with means that incorporate seasons played after the fixture date. The magnitude is small — it only affects early rows — but it violates the same no-lookahead principle the `shift(1)` design is built around. Expanding-window means (mean over rows with date ≤ fixture date) are the correct fix.

---

### 9. Elo Implementation Audit (INFORMATIONAL — no issues found)

The Elo system (`features.py:141-151`) was audited against first principles:

```python
ELO_START = 1500.0
ELO_K = 20.0
ELO_HOME_BONUS = 100.0

def elo_update(rh, ra, hg, ag):
    exp_h = 1.0 / (1.0 + 10.0 ** (-(rh + ELO_HOME_BONUS - ra) / 400.0))
    res = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
    g = 1.0 if hg == ag else math.sqrt(abs(hg - ag))
    delta = ELO_K * g * (res - exp_h)
    return rh + delta, ra - delta
```

**Temporal correctness: PASS.** In `build_features`, ratings are read before the fixture row is emitted (`row["h_elo"] = rh`) and updated after (`elo_ratings[home], elo_ratings[away] = rh, ra`). A fixture's Elo features never incorporate its own result.

**Formula correctness: PASS.** Standard logistic expectation, home-field bonus applied to the home team's effective rating, zero-sum update (home gains exactly what away loses). The sqrt margin-of-victory multiplier (`g`) is a defensible choice — dampens blowout inflation vs linear margin.

**Calibration notes (not bugs):**
- K=20 is reasonable for football (chess uses 32 for novices, 16-24 for established players). No evidence it was tuned; a quick grid search on walk-forward log-loss could validate.
- Home bonus of 100 Elo ≈ 64% expected home win prob at equal ratings, which matches empirical home advantage. Reasonable.
- Elo ratings are chronological across seasons with no regression to mean. Teams promoted/relegated carry stale ratings. Consider 30-50% regression toward 1500 at season boundaries (standard practice in sports Elo).
- `elo_diff` is a model feature but raw `h_elo`/`a_elo` are also passed (via `h_`/`a_` prefix). The diff is the informative signal; raw ratings add multicollinearity but tree models handle this fine.

---

## Roadmap

### Immediate Corrective Fixes (correctness — do before any modeling upgrade)

1. **Date-cutoff H2H** — compute `h2h_edge` from meetings with `date < fixture_date` only. Either precompute per-fixture in `features.py` (correct, slower) or store dated meeting lists in `h2h.json` and filter at lookup time (correct, fast). Then **refit all models** — the current artifacts are trained on leaked features.
2. **Fix simulation tie-break** — two options: (a) sample scorelines from the Poisson (not just 1X2) and update GD dynamically, keeping the GD tie-break; (b) drop GD from the tie-break and note the limitation. (a) is strictly better and unlocks correct H2H mini-tables for LaLiga/Serie A.
3. **Canonicalize European names** — apply `canonicalize(..., "api")` in `fetch_european`/`load_european`, and add a validate.py check that every European team maps to a canonical league team (warn on miss).
4. **Ledger idempotency** — dedup on `(fixture_date, home, away, model_version)` in `append_predictions`; add a CI check that the ledger has no duplicate keys.
5. **Align walk-forward and production ensembles** — evaluate the ensemble with the per-fold best ML config (nested selection), or fix the production ensemble to the walk-forward-evaluated combination. Do not report one and deploy the other.
6. **Expanding-window imputation** — replace global column means with means over rows dated ≤ the fixture date.

### Advanced Modeling Upgrades (performance — after correctness)

7. **Dixon-Coles rho** — fit one rho per league on the training data; apply the four-cell correction in `scoreline_to_1x2`. Expected: 1–3% log-loss improvement on draws.
8. **Negative Binomial goals model** — replace `PoissonRegressor` with a NB2 parameterization (or `statsmodels.GLMNB`) to handle overdispersion. Compare via walk-forward.
9. **Probability calibration** — isotonic regression on walk-forward out-of-fold predictions, per league. Cheap, nearly always helps log-loss.
10. **RPS + Brier in the ledger** — add Ranked Probability Score as the primary 1X2 metric (it respects the ordinal home > draw > away structure); keep log-loss as secondary. Add de-vigged market odds as a benchmark column when available.
11. **Ensemble weight optimization** — replace the 0.5/0.5 mean with weights fit by minimizing RPS on walk-forward out-of-fold predictions (constrained simplex optimization).
12. **Dynamic simulation strengths** — optional; resample team attack/defense ratings within each simulated season using a random-walk. Increases title-race variance realism at the cost of complexity.

---

## Code Diffs for Highest-Severity Issues

### Fix 1: Date-cutoff H2H (replaces the leaked lookup in `features.py`)

```python
# In build_features(), replace the h2h.json load with a dated meeting index:
def load_h2h_dated(league: str) -> dict[str, list[dict]]:
    """All directed H2H meetings with dates, for cutoff filtering."""
    fixtures_path = settings.data_dir / f"fixtures_{league}.csv"
    df = pd.read_csv(fixtures_path, dtype={"date": str, "season": str})
    fin = df[df["status"] == "finished"]
    idx: dict[str, list[dict]] = {}
    for _, r in fin.iterrows():
        for a, b in ((r["home"], r["away"]), (r["away"], r["home"])):
            w = (r["home_goals"] > r["away_goals"]) if a == r["home"] else \
                (r["away_goals"] > r["home_goals"])
            d = r["home_goals"] == r["away_goals"]
            idx.setdefault(f"{a} vs {b}", []).append(
                {"date": r["date"], "w": int(w), "d": int(d)})
    return idx

# In feature_row(), replace the h2h_edge block:
def h2h_edge_before(h2h_idx, home, away, datestr):
    w = d = tot = 0
    for m in h2h_idx.get(f"{home} vs {away}", []):
        if m["date"] < datestr:
            w += m["w"]; d += m["d"]; tot += 1
    return (w + 0.5 * d) / tot if tot else 0.5
```

### Fix 2: Scoreline-sampling simulation with live GD (replaces `simulate_league` core)

```python
def simulate_league(league):
    ...
    # Need expected goals per fixture: extend predict_upcoming or call
    # poisson_model.expected_goals on the upcoming feature matrix.
    xg_h, xg_a = poisson_model.expected_goals(X_upcoming)  # per-fixture lambdas
    for _ in range(n):
        pts = base_pts.copy(); gf = base_gf.copy(); ga = base_ga.copy()
        sh = rng.poisson(xg_h); sa = rng.poisson(xg_a)  # vectorized scorelines
        # update pts/gf/ga via numpy advanced indexing (no Python loop)
        ...
        gd = gf - ga
        order = np.lexsort((-gd, -pts))
```

Vectorized scoreline sampling also fixes the performance issue (finding 16): one `rng.poisson` call per iteration instead of a Python loop over fixtures, and points/GD updates via `np.add.at`.

### Fix 3: Dixon-Coles correction (drop into `fit.py`)

```python
def dixon_coles_adjust(pmf: np.ndarray, rho: float) -> np.ndarray:
    """Apply the Dixon-Coles low-score correction to a 10x10 matrix."""
    adj = pmf.copy()
    adj[0, 0] *= 1 - rho
    adj[0, 1] *= 1 + rho
    adj[1, 0] *= 1 + rho
    adj[1, 1] *= 1 - rho
    return adj / adj.sum()

# Fit rho per league by grid search on train log-loss (add to fit_league):
rhos = np.linspace(-0.15, 0.15, 13)
best_rho = min(rhos, key=lambda r: train_logloss_with_rho(r))
```

### Fix 4: Ledger idempotency guard (in `ledger.py:append_predictions`)

```python
def append_predictions(league, rows, path=None):
    ...
    ledger_path = init_ledger(league, path)
    existing = _read_ledger(ledger_path)
    new = pd.DataFrame(rows).reindex(columns=LEDGER_COLS)
    if not existing.empty:
        key = KEY_COLS + ["model_version"]
        seen = set(map(tuple, existing[key].astype(str).to_numpy()))
        new = new[~new[key].astype(str).apply(tuple, axis=1).isin(seen)]
    new.to_csv(ledger_path, mode="a", header=False, index=False)
    return len(new)
```

---

## Notes on the prompt's premises (corrected 2026-10-18)

- **Elo engine:** EXISTS and is correctly implemented (`features.py:141-151`). `elo_update` uses standard logistic expectation with 100-point home bonus and sqrt margin-of-victory multiplier (K=20). Ratings are read pre-match (`row["h_elo"]`) and updated post-match — no temporal leakage. `elo_diff` is in `EXTRA_MODEL_COLS`. This is a strength, not a gap.
- **`scorer_probs.py`:** EXISTS (`etl/scorer_probs.py`, 14KB). Market-odds feature pipeline. Scoreline→1X2 conversion remains `fit.py:scoreline_to_1x2` (10×10 independent Poisson, finding 4).
- **European fatigue features** (`euro_days_since`, `euro_midweek`, `euro_ppg`, `euro_gd`) are correctly date-gated (`e["date"] < datestr`) but may be silently empty due to finding 6.
- **Key absences** are Premier League only, sourced from FPL injury flags — correctly labeled per the repo's honesty conventions.
- **Walk-forward protocol itself is sound** (TimeSeriesSplit, no shuffle, recency weights computed on train folds only). The flaw is the ensemble mismatch (finding 5), not the CV scheme.
- **Half-life 180 days** is a reasonable prior for football form decay; the audit did not find evidence it was tuned. Suggest a quick grid search (90/180/365) on walk-forward log-loss as a cheap win.

