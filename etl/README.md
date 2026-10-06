# ETL

Pipeline: `extract` -> `validate` -> `features` -> `fit` -> `simulate` ->
`ai_forecaster` -> `build_site`. `refresh` runs the whole thing hash-gated.
`players` and `team_news` feed the site's player and availability sections.

Run everything with the project venv: `.venv/bin/python -m etl.<module> --help`.

## Data contracts

### data/fixtures_{league}.csv
One row per fixture per season (2023/24 through the live season).
`fixture_id` (slug `{league}-{season}-{date}-{home}-v-{away}`), `date`
(YYYY-MM-DD), `season` ("2023" = 2023/24), `league` (pl, laliga, bundesliga,
seriea, ligue1), `home`, `away` (canonical names, see etl/team_names.py),
`home_goals`, `away_goals` (empty unless finished), `status`
(finished|scheduled), `provenance`
(api_football|csv_download|csv_cached|fpl_api|schedule_reconstructed),
`api_fixture_id`,
plus nullable shot/foul columns `hs,as_,hst,ast,hf,af,hy,ay,hr,ar`
(CSV rows only; labeled shot-based, never true xG).

### data/features_{league}.csv (+ .meta.json)
One row per finished fixture, chronological. All features are shift(1)
lagged: only matches before the fixture count. Columns: identifiers
(`fixture_id,date,season,home,away,home_goals,away_goals,result`
with result 2=home,1=draw,0=away), then per-team features prefixed `h_`
(home) / `a_` (away): `w5,d5,l5,gf5,ga5,ppg_l5,ppg,gf_pg,ga_pg,gf_pg_l5,
ga_pg_l5,home_ppg,away_ppg,home_gf_pg,home_ga_pg,away_gf_pg,away_ga_pg,
cs_rate,fts_rate,momentum,shots_pg,shots_conc_pg,sot_pg,shot_diff_pg,
fouls_pg,cards_pg,rest_days,travel_km,euro_days_since,euro_midweek,
euro_ppg,euro_gd,key_absences`, plus `h2h_edge` (home perspective).
`.meta.json` carries `feature_logic_version` (sha1 of etl/features.py);
fit.py refuses features built by another version.

### data/h2h_{league}.json
Per ordered pairing `"Home vs Away"`: `last5` (date, venue, score, most
recent first) and `alltime` {w,d,l} from the first-named team's perspective.

### data/params_{league}.json + data/models/
Fit date, model version (`vYYYY-MM-DD`), data hash, feature logic version,
feature columns, chosen ML model, and the walk-forward table
(Poisson / XGB / LightGBM / ensemble / naive baseline log-loss + accuracy).
`data/models/{league}_{poisson,xgb,lgbm}.joblib` hold the fitted artifacts.

### data/predictions_ledger_{league}.csv
`fixture_date,home,away,p_home_poisson,p_draw_poisson,p_away_poisson,
p_home_ml,p_draw_ml,p_away_ml,p_home_ens,p_draw_ens,p_away_ens,model_version`.
Scoring appends `result,logloss_poisson,logloss_ml,logloss_ens,
calibration_band`.

### data/odds_{league}.csv / data/odds_history.csv
From 10,000 Monte Carlo run-outs (seed 42): `team,p_title,p_top4,
p_relegation,sims,sim_date`. History appends date-stamped snapshots.

### data/european_fixtures.jsonl
Accumulated api-football date-query results (UCL/UEL/UECL): one JSON object
per line, deduped by api fixture id.

## Sources and provenance

- 2023/24-2024/25: api-football first, football-data.co.uk CSV fallback.
- 2025/26: CSV only. Live 2026/27: FPL API (PL) + current-season CSVs.
- Future fixtures: FPL publishes them for the PL. No free source does for
  the other four leagues, so the remaining schedule is reconstructed from
  the round-robin (every ordered pairing meets once per half-season; dates
  approximate), labeled `schedule_reconstructed`.
- European congestion: api-football `/fixtures?league={2,3,848}&date=...`.
- Players: FPL (PL); official league JSON backends (others); 2024/25
  api-football topscorers as the labeled baseline.
- Team news: FPL injury/news flags (PL); Bundesliga lineup-based absence
  detection; honest "no data" labels where backends publish nothing.

Every output records its source. The site's honest-limits box states them.
