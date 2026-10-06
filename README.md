# Goal Difference

Weekly model-driven matchday analysis for Europe's top 5 leagues —
Premier League, LaLiga, Bundesliga, Serie A, Ligue 1.

Every matchday the pipeline pulls the latest results, refits two models per
league (Poisson + gradient-boosted trees, with exponential recency weighting),
runs 10,000 Monte Carlo season simulations, and rebuilds a static site:
league hubs with title odds, fixture previews with both models' probabilities,
per-team dashboards, player form, and an honest track record.

**Site:** https://nepalanurag.github.io/goal-difference/

## How it works

```
etl/extract.py   fixtures per league/season (api-football -> CSV fallback -> FPL live)
etl/validate.py  Pandera contract checks (quarantines + exits non-zero on failure)
etl/features.py  shift(1)-lagged team features (no leakage)
etl/h2h.py       head-to-head records
etl/players.py   player form: FPL (PL), official league backends (others)
etl/team_news.py availability: FPL injuries (PL), lineup absence detection (others)
etl/fit.py       per-league Poisson + XGBoost/LightGBM, walk-forward scored
etl/simulate.py  10,000 Monte Carlo run-outs -> title/top-4/relegation odds
etl/ledger.py    per-league prediction ledgers, scored weekly
etl/ai_forecaster.py  weekly memo (log-loss trends, calibration, decay watch)
etl/ai_features.py    candidate feature proposals behind flags
etl/build_site.py     static site -> docs/ (GitHub Pages)
etl/refresh.py        hash-gated daily refresh (the GitHub Action entrypoint)
```

AI is the extra layer only: the weekly performance memo and feature ideas.
It never makes the predictions.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r etl/requirements.txt
.venv/bin/python -m etl.extract      # pull fixtures (api-football key or CSVs)
.venv/bin/python -m etl.validate     # contract checks
.venv/bin/python -m etl.features     # build lagged features
.venv/bin/python -m etl.h2h          # head-to-head records
.venv/bin/python -m etl.players       # player data (keyless sources)
.venv/bin/python -m etl.team_news    # availability data
.venv/bin/python -m etl.fit          # fit Poisson + ML per league
.venv/bin/python -m etl.simulate     # season simulations
.venv/bin/python -m etl.build_site    # render docs/
.venv/bin/python -m pytest tests/ -q  # test suite
```

Or `dvc repro` for the extract -> validate -> features stages.

Every CLI has `--help` and fails loudly with a clear error. Logs are
structured JSON on stdout; no `print()` anywhere in `etl/`.

## Data sources (all free)

| League | 2023/24-2024/25 | 2025/26 | Live 2026/27 |
|---|---|---|---|
| Premier League | api-football | CSV | FPL API |
| LaLiga | api-football | CSV | CSV |
| Bundesliga | api-football | CSV | CSV |
| Serie A | api-football | CSV | CSV |
| Ligue 1 | api-football | CSV | CSV |

- **api-football** (free tier, 100 req/day): historical fixtures + 2024/25
  topscorers. Key via `API_FOOTBALL_KEY` env var (CI) or the local
  `custom.api-football` connector. Never hardcoded, never logged.
- **football-data.co.uk CSVs**: fallback for history, only source for
  2025/26, live source for all leagues (updated ~a day after matches).
- **FPL API** (`fantasy.premierleague.com/api/`, no key): live PL fixtures,
  player form, injuries, suspensions. Unofficial, no SLA, stable for years.
- **Official league JSON backends** (no key, the leagues' own website feeds):
  LaLiga (`apim.laliga.com`, key re-read from the page config at runtime),
  Bundesliga (public Firebase), Serie A (`api-sdp.legaseriea.it`),
  Ligue 1 (`ma-api.ligue1.fr`). Validated, cached raw, never hard-fail;
  each league degrades to the labeled topscorers fallback.
- **European congestion**: api-football `/fixtures?league={2,3,848}&date=...`
  accumulated into `data/european_fixtures.jsonl` (~9 req/day in CI).

football-data.org is not used (no free tier). Nothing paid anywhere.

## Models

- **Statistical:** Poisson goal regressions on the lagged features (separate
  home/away), converted to 1X2 via a scoreline matrix.
- **ML:** XGBoost / LightGBM on the same features; the better walk-forward
  log-loss wins per league.
- **Ensemble:** plain mean of the two — the headline probability.

Every refresh refits on the full history with exponential recency weighting
(half-life 180 days). Walk-forward (time-series splits) scores Poisson vs
each ML config vs ensemble vs a naive historical-rates baseline; the
track-record page shows all of them, including leagues where nothing beats
the baseline.

## Refresh

`.github/workflows/refresh.yml` runs daily at 06:00 America/Los_Angeles.
`etl/refresh.py` hashes the finished-fixture set; nothing changed → exits
quietly, so it effectively runs once per matchday. On change it rebuilds
everything and commits `data/` + `docs/` to main.

CI needs one repo secret: `API_FOOTBALL_KEY` (European fixture accumulation,
~9 requests/day). Everything else is keyless.

## Honest limits

- Probabilities are model outputs, not betting advice.
- CSV live data lags ~a day; FPL (PL) is same-day.
- FPL and the league backends are unofficial feeds.
- Team news outside the PL is absence detection from lineups, labeled
  "reason unconfirmed" — never called an injury.
- Shot stats are shot-based, never true xG.

## Layout

```
etl/            pipeline modules + requirements.txt + README (data contracts)
tests/          pytest suite (real assertions, fixtures)
data/           generated artifacts (fixtures, features, params, odds, ledgers)
docs/           generated static site (GitHub Pages)
.github/workflows/  ci.yml (tests) + refresh.yml (daily)
dvc.yaml        extract -> validate -> features stages
Dockerfile      pinned Python 3.12 runtime
```
