# Goal Difference

Every matchday I rebuild a matchday analysis site for Europe's top 5 leagues:
Premier League, LaLiga, Bundesliga, Serie A, Ligue 1. Title odds, fixture
previews, team dashboards, player form. Two models per league (Poisson and
gradient-boosted trees), a 10,000-run Monte Carlo season simulation, and a
track record page that keeps me honest by scoring every model against a
naive baseline.

**Live site:** https://nepalanurag.github.io/goal-difference/

## Key results

Walk-forward log-loss (lower is better), refit on the 2026-10-07 refresh:

| League | Poisson | ML (XGBoost/LightGBM) | Ensemble | Naive baseline |
|---|---|---|---|---|
| Premier League | 1.0118 | 0.9430 | 0.9396 | 1.0849 |
| LaLiga | 1.0308 | 0.9364 | 0.9368 | 1.0661 |
| Bundesliga | 1.0663 | 0.9255 | 0.9347 | 1.0824 |
| Serie A | 1.0342 | 0.9533 | 0.9514 | 1.0943 |
| Ligue 1 | 1.0766 | 0.9303 | 0.9457 | 1.0728 |

The ML model and the ensemble beat the baseline in all five leagues. Poisson
beats it in four of five: in Ligue 1, Poisson (1.0766) comes in slightly
worse than the baseline (1.0728), and the track record page shows that too
instead of hiding it.

Every prediction goes into a per-league ledger and gets scored as results
come in. The ledger is still young, so the long-run scored numbers are
still accumulating on the live track record page (log-loss trends,
calibration, and a model-decay watch).

## How to run

```bash
python3 -m venv .venv && .venv/bin/pip install -r etl/requirements.txt
.venv/bin/python -m etl.extract      # pull fixtures (api-football key or CSVs)
.venv/bin/python -m etl.validate    # contract checks, quarantines bad rows
.venv/bin/python -m etl.features    # build lagged features
.venv/bin/python -m etl.fit         # fit Poisson + ML per league
.venv/bin/python -m etl.simulate    # season simulations
.venv/bin/python -m etl.build_site  # render docs/ (GitHub Pages)
.venv/bin/python -m pytest tests/ -q  # test suite
```

Or `dvc repro` for the extract -> validate -> features stages. Every CLI has
`--help` and fails loudly with a clear error. Logs are structured JSON on
stdout.

A GitHub Action refreshes daily at 06:00 America/Los_Angeles. The refresh is
hash-gated on finished fixtures, so it effectively runs once per matchday.
CI needs one repo secret: `API_FOOTBALL_KEY` (European fixture accumulation,
~9 requests/day). Everything else is keyless.

## How the models work

- Per-league Poisson goal regressions on shift(1)-lagged team features (no
  leakage), converted to 1X2 through a scoreline matrix.
- XGBoost / LightGBM on the same features; the better walk-forward log-loss
  wins per league.
- The headline probability is the plain mean of the two.
- Every refresh refits on the full history with exponential recency weighting
  (half-life 180 days).

AI is the extra layer only: the weekly performance memo and feature ideas.
It never makes the predictions.

## Data sources (all free)

| League | 2023/24-2024/25 | 2025/26 | Live 2026/27 |
|---|---|---|---|
| Premier League | api-football | CSV | FPL API |
| LaLiga | api-football | CSV | CSV |
| Bundesliga | api-football | CSV | CSV |
| Serie A | api-football | CSV | CSV |
| Ligue 1 | api-football | CSV | CSV |

- **api-football** (free tier, 100 req/day): historical fixtures + 2024/25
  topscorers. Key via `API_FOOTBALL_KEY` env var. Never hardcoded, never logged.
- **football-data.co.uk CSVs**: fallback for history, only source for
  2025/26, live source for all leagues (updated ~a day after matches).
- **FPL API** (fantasy.premierleague.com/api/, no key): live PL fixtures,
  player form, injuries, suspensions. Unofficial, no SLA, stable for years.
- **Official league JSON backends** (no key, the leagues' own website feeds):
  LaLiga (apim.laliga.com), Bundesliga (public Firebase), Serie A
  (api-sdp.legaseriea.it), Ligue 1 (ma-api.ligue1.fr). Validated, cached raw,
  never hard-fail; each league degrades to the labeled topscorers fallback.
- **European congestion**: api-football fixtures for leagues 2, 3, 848
  accumulated into `data/european_fixtures.jsonl`.

football-data.org is not used (no free tier). Nothing paid anywhere.

## Honest limits

- Probabilities are model outputs, not betting advice.
- CSV live data lags ~a day; FPL (PL) is same-day.
- FPL and the league backends are unofficial feeds.
- Team news outside the PL is absence detection from lineups, labeled
  "reason unconfirmed" — never called an injury.
- Shot stats are shot-based, never true xG.

## Layout

```
etl/            pipeline modules + requirements.txt (data contracts inside)
tests/          pytest suite (real assertions, fixtures)
data/           generated artifacts (fixtures, features, params, odds, ledgers)
docs/           generated static site (GitHub Pages)
.github/workflows/  ci.yml (tests) + refresh.yml (daily)
dvc.yaml        extract -> validate -> features stages
Dockerfile      pinned Python 3.12 runtime
```
