# Feature documentation

How every model feature in `data/features_{league}.csv` is built, what it
means, and how missing values are handled. One code path builds features
for training and prediction (`etl.features.build_features`), so the
columns documented here are exactly what the models train on.

Global rule: every feature is lagged. A fixture's row only uses matches
played **before** its date (shift(1) histories, chronologically updated
ratings, closing odds known pre-kickoff). A fixture never sees its own
result.

Versioning: `feature_logic_version()` is the sha1 of `etl/features.py`
(first 12 chars). The 8-char prefix names the versioned Parquet snapshot
`data/lake/features/{league}/features_v{VERSION}.parquet`. `etl.fit`
refuses to train on a features CSV built by a different version.

Feature logic: `etl/features.py` (`TeamHistory`, `build_features`).
Model column selection: `etl.features.feature_columns`.
Consumers: `etl/fit.py` (XGBoost/LightGBM), `etl/predict.py` (upcoming
fixtures), site pages read the same CSVs.

## Row-level columns (not model features)

| Column | Meaning |
|---|---|
| fixture_id | Stable id for the fixture |
| date | Kickoff date (ISO) |
| season | Season the fixture belongs to, e.g. "2025" |
| home, away | Canonical team names |
| home_goals, away_goals | Final score (train mode only) |
| result | 2 = home win, 1 = draw, 0 = away win (train mode only) |

## Form features (per team, h_ / a_ prefix)

Computed by `TeamHistory.features()` in `etl/features.py` from the team's
own chronological history, excluding the current fixture.

| Feature | Definition | Window |
|---|---|---|
| w5, d5, l5 | Wins, draws, losses | Last 5 matches |
| gf5, ga5 | Goals for, goals against | Last 5 matches |
| ppg_l5 | Points per game | Last 5 matches |
| ppg | Points per game | Whole season to date |
| gf_pg, ga_pg | Goals for/against per game | Whole season to date |
| gf_pg_l5, ga_pg_l5 | Goals for/against per game | Last 5 matches |
| home_ppg | Points per game at home | Season to date, home matches |
| away_ppg | Points per game away | Season to date, away matches |
| home_gf_pg, home_ga_pg | Goals for/against per home game | Season to date, home matches |
| away_gf_pg, away_ga_pg | Goals for/against per away game | Season to date, away matches |
| cs_rate | Share of matches with 0 goals conceded | Season to date |
| fts_rate | Share of matches with 0 goals scored | Season to date |
| momentum | ppg_l5 minus ppg (form vs season average) | 5-match vs season |

Null handling: teams with no history yet (first fixtures of a season)
get neutral imputation, see "Global null handling" below. Venue-split
features fall back to the overall season value when the team has not
played at that venue yet.

## Shot and discipline features (per team, h_ / a_ prefix)

From `stats_for()` in `etl/features.py`, averaged per game over the
team's season history. These are shot-based stats from the raw
football-data.co.uk feed, **not** true expected goals.

| Feature | Definition | Window |
|---|---|---|
| shots_pg | Shots per game | Season to date |
| shots_conc_pg | Shots conceded per game | Season to date |
| shot_diff_pg | shots_pg minus shots_conc_pg | Season to date |
| sot_pg | Shots on target per game | Season to date |
| fouls_pg | Fouls per game | Season to date |
| cards_pg | Cards per game (yellow = 1, red = 2) | Season to date |

Null handling: a match with missing shot data is skipped in the average.
If a team has no shot data at all yet, the column gets neutral
imputation.

## Ratings

| Feature | Definition | Computed by |
|---|---|---|
| h_elo, a_elo | ClubElo-style rating of each team | `elo_update()` in `etl/features.py` |
| elo_diff | h_elo minus a_elo | `build_features()` |

Ratings start at 1500 for new teams and are updated chronologically as
fixtures are processed, so a row only ever sees pre-match ratings.
Update rule: k=20, +100 home advantage, goal-margin weighting
sqrt(margin) for decisive results (1.0 for draws). Because the update
happens after the row is emitted, the row for fixture N never contains
the rating change caused by fixture N.

## Head-to-head

| Feature | Definition | Window |
|---|---|---|
| h2h_edge | Home team's all-time points share vs this opponent: (wins + 0.5 x draws) / total | All history in `data/h2h_{league}.json` |

Null handling: 0.5 (neutral) when the teams have no recorded history.

## Travel and rest

| Feature | Definition | Null handling |
|---|---|---|
| h_travel_km | Always 0.0 (home team does not travel) | n/a |
| a_travel_km | Haversine km between the two stadium cities (`CITY_COORDS`) | 0.0 when a city is missing |
| h_rest_days, a_rest_days | Days since the team's previous fixture | 7 for a team's first fixture; capped at 30 |

## European congestion and strength

From `data/european_fixtures.jsonl` (`load_european()`). Only European
fixtures strictly before the fixture date count.

| Feature | Definition | Null handling |
|---|---|---|
| h_euro_days_since, a_euro_days_since | Days since the team's last European fixture | 999 when the team has none |
| h_euro_midweek, a_euro_midweek | 1 when the last European fixture was within 4 days before kickoff | 0 when none |
| h_euro_ppg, a_euro_ppg | Points per game in Europe this season (season starts July 1) | 1.0 when none |
| h_euro_gd, a_euro_gd | Goal difference in Europe this season | 0 when none |

## Key absences (Premier League only)

| Feature | Definition |
|---|---|
| h_key_absences, a_key_absences | Count of key absent players from `data/team_news_pl.json` (`load_key_absences()`) |

Other leagues: always 0.

## Market odds

De-vigged closing odds from the raw football-data.co.uk CSVs
(`load_devigged_odds()` in `etl/features.py`). Closing odds
(B365CH/CD/CA) preferred, opening odds (B365H/D/A) as fallback.
De-vigging: p = (1/odds) / sum(1/odds), so the three sum to 1.
Keyed by (home, away, date); odds are published before kickoff, so no
leakage.

| Feature | Definition | Null handling |
|---|---|---|
| odds_p_home, odds_p_draw, odds_p_away | De-vigged market probability | NaN when no odds row matches, then imputed to 1/3 |
| odds_available | 1 when odds were found, else 0 | 0 |

## Global null handling

After all rows are built, every remaining NaN in a model column is
filled: odds probabilities with 1/3 each (the neutral three-way split),
all other columns with the column mean, or 0.0 when a column is entirely
empty. Early-season rows therefore carry league-average values rather
than NaN. The `result` label is never imputed.
