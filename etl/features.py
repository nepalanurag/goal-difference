"""Features: team-performance features for every finished fixture.

Every feature is lagged with shift(1): only matches played BEFORE the fixture
count, so there is no leakage. Output: data/features_{league}.csv plus
data/features_{league}.meta.json carrying FEATURE_LOGIC_VERSION (sha1 of this
file). fit.py refuses to train on features built by another version.

Feature families: rolling 5-match form, venue-split expanding form, attack /
defense ratings (season + last-5), shot dominance (labeled shot-based, never
true xG), clean-sheet / failed-to-score rates, momentum, discipline, travel
fatigue (stadium-city coords + rest days), H2H edge, European congestion and
strength signals, key absences (Premier League only), ClubElo-style ratings
(h_elo, a_elo, elo_diff; k=20, +100 home bonus, sqrt goal-margin weighting,
computed chronologically), and de-vigged closing odds from the raw
football-data.co.uk CSVs (odds_p_home/draw/away, odds_available flag).

Usage: python -m etl.features [--leagues pl laliga ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import settings
from .logging_setup import get_logger
from .storage import (features_lake_path, features_lake_versioned_path,
                      write_parquet)
from .team_names import CANONICAL

log = get_logger(__name__)

FORM_WINDOW = 5


def feature_logic_version() -> str:
    return hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:12]


# ----------------------------------------------------------------------------
# City coordinates (stadium cities) for travel-fatigue distances. City-level
# precision is plenty for a fatigue feature; haversine km between cities.
# ----------------------------------------------------------------------------
CITY_COORDS: dict[str, tuple[float, float]] = {
    # Premier League
    "Arsenal": (51.557, -0.106), "Aston Villa": (52.509, -1.885),
    "Bournemouth": (50.735, -1.838), "Brentford": (51.491, -0.293),
    "Brighton": (50.861, -0.083), "Burnley": (53.789, -2.23),
    "Chelsea": (51.482, -0.191), "Crystal Palace": (51.398, -0.086),
    "Everton": (53.439, -2.966), "Fulham": (51.475, -0.221),
    "Coventry City": (52.448, -1.498), "Hull City": (53.746, -0.367),
    "Ipswich Town": (52.055, 1.161),
    "Leeds": (53.778, -1.572),
    "Leicester": (52.62, -1.142), "Liverpool": (53.431, -2.966),
    "Luton": (51.885, -0.436), "Man City": (53.483, -2.2),
    "Man United": (53.463, -2.291), "Newcastle": (54.975, -1.614),
    "Nott'm Forest": (52.94, -1.137), "Sheffield United": (53.37, -1.471),
    "Southampton": (50.861, -1.391), "Sunderland": (54.914, -1.388),
    "Tottenham": (51.604, -0.066), "West Ham": (51.539, 0.016),
    "Wolves": (52.59, -2.13),
    # LaLiga
    "Alaves": (42.847, -2.675), "Almeria": (36.839, -2.461),
    "Ath Bilbao": (43.264, -2.949), "Ath Madrid": (40.437, -3.599),
    "Barcelona": (41.387, 2.123), "Betis": (37.384, -5.971),
    "Cadiz": (36.529, -6.277), "Celta": (42.212, -8.74),
    "Elche": (38.269, -0.698), "Espanyol": (41.347, 2.075),
    "Getafe": (40.308, -3.714), "Girona": (41.979, 2.823),
    "Granada": (37.161, -3.598), "La Coruna": (43.371, -8.422),
    "Las Palmas": (28.101, -15.455),
    "Malaga": (36.72, -4.419), "Santander": (43.462, -3.804),
    "Leganes": (40.328, -3.766), "Levante": (39.475, -0.375),
    "Mallorca": (39.59, 2.63), "Osasuna": (42.797, -1.637),
    "Oviedo": (43.361, -5.859), "Rayo Vallecano": (40.391, -3.658),
    "Real Madrid": (40.453, -3.688), "Real Sociedad": (43.301, -1.974),
    "Sevilla": (37.384, -5.971), "Valencia": (39.475, -0.375),
    "Valladolid": (41.643, -4.729), "Villarreal": (39.944, -0.103),
    # Bundesliga
    "Augsburg": (48.324, 10.886), "Dortmund": (51.493, 7.452),
    "M'gladbach": (51.174, 6.383), "Bayern Munich": (48.219, 11.625),
    "Bochum": (51.484, 7.068), "Darmstadt": (49.872, 8.654),
    "Ein Frankfurt": (50.068, 8.645), "Freiburg": (47.999, 7.893),
    "Heidenheim": (48.678, 10.154), "Hoffenheim": (49.239, 8.885),
    "Holstein Kiel": (54.343, 10.123), "FC Koln": (50.933, 6.875),
    "Hamburg": (53.587, 9.899), "Elversberg": (49.316, 7.142),
    "Paderborn": (51.719, 8.747), "Schalke 04": (51.554, 7.068),
    "Fortuna Dusseldorf": (51.261, 6.733),
    "Leverkusen": (51.038, 6.979), "Mainz": (49.984, 8.224),
    "RB Leipzig": (51.346, 12.348), "St Pauli": (53.554, 9.917),
    "Stuttgart": (48.792, 9.232), "Union Berlin": (52.457, 13.568),
    "Werder Bremen": (53.066, 8.837), "Wolfsburg": (52.428, 10.804),
    # Serie A
    "Atalanta": (45.709, 9.681), "Bologna": (44.492, 11.309),
    "Cagliari": (39.2, 9.136), "Como": (45.814, 9.077),
    "Cremonese": (45.142, 10.049), "Empoli": (43.719, 10.947),
    "Fiorentina": (43.781, 11.283), "Frosinone": (41.634, 13.324),
    "Genoa": (44.416, 8.952), "Inter": (45.478, 9.124),
    "Juventus": (45.109, 7.641), "Lazio": (41.934, 12.454),
    "Lecce": (40.365, 18.201), "Milan": (45.478, 9.124),
    "Monza": (45.615, 9.209), "Napoli": (40.827, 14.193),
    "Parma": (44.791, 10.335), "Pisa": (43.727, 10.415),
    "Roma": (41.934, 12.454), "Salernitana": (40.679, 14.834),
    "Sassuolo": (44.698, 10.832), "Torino": (45.041, 7.65),
    "Udinese": (46.075, 13.212), "Venezia": (45.475, 12.372),
    "Verona": (45.435, 10.969),
    # Ligue 1
    "Angers": (47.461, -0.53), "Auxerre": (47.796, 3.583),
    "Brest": (48.39, -4.486), "Clermont": (45.781, 3.118),
    "Le Havre": (49.494, 0.107), "Lens": (50.433, 2.814),
    "Lille": (50.612, 3.13), "Lorient": (47.748, -3.366),
    "Lyon": (45.766, 4.981), "Marseille": (43.269, 5.396),
    "Metz": (49.108, 6.169), "Monaco": (43.728, 7.415),
    "Montpellier": (43.613, 3.807), "Nantes": (47.256, -1.525),
    "Nice": (43.703, 7.266), "Paris SG": (48.841, 2.253),
    "Paris FC": (48.841, 2.379), "Le Mans": (48.007, 0.199),
    "Troyes": (48.298, 4.079),
    "Reims": (49.26, 4.026), "Rennes": (48.107, -1.643),
    "St Etienne": (45.461, 4.39), "Strasbourg": (48.56, 7.755),
    "Toulouse": (43.583, 1.434),
}


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


# ----------------------------------------------------------------------------
# ClubElo-style ratings. k=20, +100 home bonus, goal-margin weighting
# sqrt(margin) for decisive results (draws use 1.0). New teams start at 1500.
# Ratings are updated chronologically as fixtures are processed, so a row's
# h_elo/a_elo only ever reflect matches played before that fixture.
# ----------------------------------------------------------------------------
ELO_START = 1500.0
ELO_K = 20.0
ELO_HOME_BONUS = 100.0


def elo_update(rh: float, ra: float, hg: int, ag: int) -> tuple[float, float]:
    exp_h = 1.0 / (1.0 + 10.0 ** (-(rh + ELO_HOME_BONUS - ra) / 400.0))
    res = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
    g = 1.0 if hg == ag else math.sqrt(abs(hg - ag))
    delta = ELO_K * g * (res - exp_h)
    return rh + delta, ra - delta


# ----------------------------------------------------------------------------
# De-vigged market odds from the raw football-data.co.uk CSVs. Closing odds
# (B365CH/CD/CA) preferred, opening odds (B365H/D/A) as fallback. De-vig:
# p = (1/odds) / sum(1/odds). Keyed by (home, away, date) with canonical
# team names; rows without odds get NaN (imputed later) and odds_available=0.
# ----------------------------------------------------------------------------
RAW_CSV_ALIASES: dict[str, dict[str, str]] = {
    # The 2025/26 LaLiga CSV uses shortened spellings.
    "laliga": {"Espanol": "Espanyol", "Sociedad": "Real Sociedad",
               "Vallecano": "Rayo Vallecano"},
}

ODDS_COLS = ("B365CH", "B365CD", "B365CA", "B365H", "B365D", "B365A")


def load_devigged_odds(league: str) -> dict[tuple[str, str, str], tuple[float, float, float]]:
    """(home, away, date) -> de-vigged (p_home, p_draw, p_away)."""
    aliases = RAW_CSV_ALIASES.get(league, {})
    out: dict[tuple[str, str, str], tuple[float, float, float]] = {}
    for path in sorted(settings.raw_dir.glob(f"csv_{league}_20*.csv")):
        try:
            raw = pd.read_csv(path, usecols=["Date", "HomeTeam", "AwayTeam",
                                             *ODDS_COLS])
        except (ValueError, FileNotFoundError):
            continue
        raw["datestr"] = pd.to_datetime(raw["Date"], dayfirst=True).dt.date.astype(str)
        raw["home"] = raw["HomeTeam"].map(lambda t: aliases.get(t, t))
        raw["away"] = raw["AwayTeam"].map(lambda t: aliases.get(t, t))
        for _, r in raw.iterrows():
            close = [r["B365CH"], r["B365CD"], r["B365CA"]]
            open_ = [r["B365H"], r["B365D"], r["B365A"]]
            trio = close if all(pd.notna(close)) else open_
            if not all(pd.notna(trio)) or any(float(o) <= 1.0 for o in trio):
                continue
            inv = np.array([1.0 / float(o) for o in trio])
            p = inv / inv.sum()
            out[(r["home"], r["away"], r["datestr"])] = (
                float(p[0]), float(p[1]), float(p[2]))
    log.info("odds_loaded", league=league, n=len(out))
    return out


# Model feature columns: everything the GBM / GLM trains on.
EXTRA_MODEL_COLS = ["h2h_edge", "elo_diff",
                    "odds_p_home", "odds_p_draw", "odds_p_away", "odds_available"]

# Neutral fill for columns where a column mean is meaningless.
NEUTRAL_DEFAULTS = {"odds_p_home": 1.0 / 3.0, "odds_p_draw": 1.0 / 3.0,
                    "odds_p_away": 1.0 / 3.0}


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if (c.startswith(("h_", "a_")) and c != "h2h_edge")
            or c in EXTRA_MODEL_COLS]


# ----------------------------------------------------------------------------
# Feature computation
# ----------------------------------------------------------------------------
class TeamHistory:
    """Chronological match history for one team; features read shift(1)."""

    def __init__(self) -> None:
        self.matches: list[dict] = []

    def add(self, date: str, venue: str, gf: int, ga: int,
            stats: dict, opp: str) -> None:
        # gf/ga are always from THIS team's perspective.
        if gf > ga:
            w, d, l = 1, 0, 0
        elif gf == ga:
            w, d, l = 0, 1, 0
        else:
            w, d, l = 0, 0, 1
        self.matches.append({
            "date": date, "venue": venue, "gf": gf, "ga": ga,
            "w": w, "d": d, "l": l, "opp": opp, **stats,
        })

    def _last(self, n: int) -> list[dict]:
        return self.matches[-n:] if n else []

    def features(self) -> dict:
        m = self.matches
        feats: dict[str, float] = {}
        if not m:
            return feats
        last5 = self._last(FORM_WINDOW)
        feats["w5"] = sum(x["w"] for x in last5)
        feats["d5"] = sum(x["d"] for x in last5)
        feats["l5"] = sum(x["l"] for x in last5)
        feats["gf5"] = sum(x["gf"] for x in last5)
        feats["ga5"] = sum(x["ga"] for x in last5)
        feats["ppg_l5"] = (feats["w5"] * 3 + feats["d5"]) / max(len(last5), 1)
        n = len(m)
        feats["ppg"] = sum(x["w"] * 3 + x["d"] for x in m) / n
        feats["gf_pg"] = sum(x["gf"] for x in m) / n
        feats["ga_pg"] = sum(x["ga"] for x in m) / n
        feats["gf_pg_l5"] = feats["gf5"] / max(len(last5), 1)
        feats["ga_pg_l5"] = feats["ga5"] / max(len(last5), 1)
        home_m = [x for x in m if x["venue"] == "H"]
        away_m = [x for x in m if x["venue"] == "A"]
        feats["home_ppg"] = (sum(x["w"] * 3 + x["d"] for x in home_m) / len(home_m)) if home_m else feats["ppg"]
        feats["away_ppg"] = (sum(x["w"] * 3 + x["d"] for x in away_m) / len(away_m)) if away_m else feats["ppg"]
        feats["home_gf_pg"] = (sum(x["gf"] for x in home_m) / len(home_m)) if home_m else feats["gf_pg"]
        feats["home_ga_pg"] = (sum(x["ga"] for x in home_m) / len(home_m)) if home_m else feats["ga_pg"]
        feats["away_gf_pg"] = (sum(x["gf"] for x in away_m) / len(away_m)) if away_m else feats["gf_pg"]
        feats["away_ga_pg"] = (sum(x["ga"] for x in away_m) / len(away_m)) if away_m else feats["ga_pg"]
        feats["cs_rate"] = sum(1 for x in m if x["ga"] == 0) / n
        feats["fts_rate"] = sum(1 for x in m if x["gf"] == 0) / n
        feats["momentum"] = feats["ppg_l5"] - feats["ppg"]
        for key in ("shots", "shots_conc", "sot", "fouls", "cards"):
            vals = [x[key] for x in m if x.get(key) is not None]
            feats[f"{key}_pg"] = sum(vals) / len(vals) if vals else np.nan
        feats["shot_diff_pg"] = (
            (feats["shots_pg"] - feats["shots_conc_pg"])
            if not (np.isnan(feats["shots_pg"]) or np.isnan(feats["shots_conc_pg"])) else np.nan
        )
        return feats


def load_european() -> dict[str, list[dict]]:
    """Per-team European fixture history from the accumulated jsonl."""
    path = settings.data_dir / "european_fixtures.jsonl"
    per_team: dict[str, list[dict]] = {}
    if not path.exists():
        return per_team
    for line in path.read_text().splitlines():
        try:
            fx = json.loads(line)
        except json.JSONDecodeError:
            continue
        for side, gf_key, ga_key in (("home", "home_goals", "away_goals"),
                                     ("away", "away_goals", "home_goals")):
            team = fx[side]
            gf, ga = fx[gf_key], fx[ga_key]
            pts = 3 if (gf or 0) > (ga or 0) else (1 if gf == ga else 0)
            per_team.setdefault(team, []).append({
                "date": fx["date"], "gf": gf or 0, "ga": ga or 0, "pts": pts,
            })
    for v in per_team.values():
        v.sort(key=lambda x: x["date"])
    return per_team


def load_key_absences() -> dict[str, int]:
    """Key-absence counts per team (Premier League, from team_news_pl.json)."""
    path = settings.data_dir / "team_news_pl.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return {team: info.get("key_absences", 0)
            for team, info in data.get("teams", {}).items()}


def build_features(league: str, mode: str = "train") -> tuple[pd.DataFrame, dict]:
    """Build lagged feature rows.

    mode="train": one row per finished fixture (for model fitting).
    mode="predict": histories are built from all finished fixtures, then one
    row per scheduled fixture is emitted (no goals/result columns).
    """
    fixtures_path = settings.data_dir / f"fixtures_{league}.csv"
    df = pd.read_csv(fixtures_path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)

    h2h_path = settings.data_dir / f"h2h_{league}.json"
    h2h = json.loads(h2h_path.read_text()) if h2h_path.exists() else {}
    euro = load_european()
    absences = load_key_absences() if league == "pl" else {}
    odds_map = load_devigged_odds(league)

    histories: dict[str, TeamHistory] = {}
    last_date: dict[str, str] = {}
    elo_ratings: dict[str, float] = {}
    rows: list[dict] = []

    def stats_for(is_home: bool, r) -> dict:
        shots = r["hs"] if is_home else r["as_"]
        shots_c = r["as_"] if is_home else r["hs"]
        sot = r["hst"] if is_home else r["ast"]
        fouls = r["hf"] if is_home else r["af"]
        cards = ((r["hy"] or 0) + (r["hr"] or 0) * 2) if is_home else (
            (r["ay"] or 0) + (r["ar"] or 0) * 2)
        num = lambda v: None if pd.isna(v) else float(v)
        return {
            "shots": num(shots), "shots_conc": num(shots_c), "sot": num(sot),
            "fouls": num(fouls), "cards": num(cards),
        }

    def feature_row(fx, home: str, away: str, datestr: str) -> dict:
        hh = histories.setdefault(home, TeamHistory())
        ah = histories.setdefault(away, TeamHistory())
        hf, af = hh.features(), ah.features()
        row: dict = {
            "fixture_id": fx["fixture_id"],
            "date": datestr,
            "season": str(fx["season"]),
            "home": home,
            "away": away,
        }
        if mode == "train":
            row["home_goals"] = int(fx["home_goals"])
            row["away_goals"] = int(fx["away_goals"])
            row["result"] = 2 if fx["home_goals"] > fx["away_goals"] else (
                1 if fx["home_goals"] == fx["away_goals"] else 0)
        for prefix, feats in (("h_", hf), ("a_", af)):
            for k, v in feats.items():
                row[f"{prefix}{k}"] = v
        key = f"{home} vs {away}"
        edge = 0.5
        if key in h2h:
            at = h2h[key]["alltime"]
            tot = at["w"] + at["d"] + at["l"]
            edge = (at["w"] + 0.5 * at["d"]) / tot if tot else 0.5
        row["h2h_edge"] = edge
        hc, ac = CITY_COORDS.get(home), CITY_COORDS.get(away)
        row["h_travel_km"] = 0.0
        row["a_travel_km"] = haversine_km(ac, hc) if hc and ac else 0.0
        for prefix, team in (("h_", home), ("a_", away)):
            if team in last_date:
                delta = (datetime.fromisoformat(datestr).date()
                         - datetime.fromisoformat(last_date[team]).date()).days
                row[f"{prefix}rest_days"] = min(delta, 30)
            else:
                row[f"{prefix}rest_days"] = 7
        for prefix, team in (("h_", home), ("a_", away)):
            played = [e for e in euro.get(team, []) if e["date"] < datestr]
            if played:
                last = played[-1]
                gap = (datetime.fromisoformat(datestr).date()
                       - datetime.fromisoformat(last["date"]).date()).days
                row[f"{prefix}euro_days_since"] = gap
                row[f"{prefix}euro_midweek"] = 1 if gap <= 4 else 0
                season_euro = [e for e in played
                               if e["date"] >= f"{row['season']}-07-01"]
                row[f"{prefix}euro_ppg"] = (
                    sum(e["pts"] for e in season_euro) / len(season_euro))
                row[f"{prefix}euro_gd"] = sum(e["gf"] - e["ga"] for e in season_euro)
            else:
                row[f"{prefix}euro_days_since"] = 999
                row[f"{prefix}euro_midweek"] = 0
                row[f"{prefix}euro_ppg"] = 1.0
                row[f"{prefix}euro_gd"] = 0
        row["h_key_absences"] = absences.get(home, 0)
        row["a_key_absences"] = absences.get(away, 0)
        # Elo: pre-match ratings only (chronological, no leakage).
        rh = elo_ratings.get(home, ELO_START)
        ra = elo_ratings.get(away, ELO_START)
        row["h_elo"] = rh
        row["a_elo"] = ra
        row["elo_diff"] = rh - ra
        # De-vigged market odds (closing odds, known pre-kickoff).
        probs = odds_map.get((home, away, datestr))
        if probs is not None:
            row["odds_p_home"], row["odds_p_draw"], row["odds_p_away"] = probs
            row["odds_available"] = 1
        else:
            row["odds_p_home"] = np.nan
            row["odds_p_draw"] = np.nan
            row["odds_p_away"] = np.nan
            row["odds_available"] = 0
        return row

    for _, fx in df.iterrows():
        datestr = fx["date"].date().isoformat()
        home, away = fx["home"], fx["away"]
        if fx["status"] != "finished":
            if mode == "predict":
                rows.append(feature_row(fx, home, away, datestr))
            continue
        if mode == "train":
            rows.append(feature_row(fx, home, away, datestr))
        hg, ag = int(fx["home_goals"]), int(fx["away_goals"])
        histories.setdefault(home, TeamHistory()).add(
            datestr, "H", hg, ag, stats_for(True, fx), away)
        histories.setdefault(away, TeamHistory()).add(
            datestr, "A", ag, hg, stats_for(False, fx), home)
        rh, ra = elo_update(elo_ratings.get(home, ELO_START),
                            elo_ratings.get(away, ELO_START), hg, ag)
        elo_ratings[home], elo_ratings[away] = rh, ra
        last_date[home] = datestr
        last_date[away] = datestr

    feats_df = pd.DataFrame(rows)
    # Neutral imputation for teams with no history yet (early rows): column
    # means. Shot/foul-based columns are labeled shot-based, never true xG.
    # Odds columns with no data at all (predict mode) get 1/3 each.
    for col in feature_columns(feats_df):
        if feats_df[col].isna().any():
            default = NEUTRAL_DEFAULTS.get(col)
            if default is None:
                mean = feats_df[col].mean()
                default = mean if pd.notna(mean) else 0.0
            feats_df[col] = feats_df[col].fillna(default)

    data_hash = hashlib.sha1(
        pd.read_csv(fixtures_path, usecols=["fixture_id", "home_goals", "away_goals"])
        .to_csv(index=False).encode()).hexdigest()[:12]
    meta = {
        "feature_logic_version": feature_logic_version(),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": len(feats_df),
        "data_hash": data_hash,
    }
    return feats_df, meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build lagged team features.")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        choices=settings.league_order)
    args = parser.parse_args(argv)
    for league in args.leagues:
        feats_df, meta = build_features(league)
        version8 = meta["feature_logic_version"][:8]
        out = settings.data_dir / f"features_{league}.csv"
        feats_df.to_csv(out, index=False)
        # Versioned snapshot (immutable, addressable by feature code version)
        # plus the unversioned pointer that existing consumers read.
        write_parquet(feats_df, features_lake_versioned_path(league, version8))
        write_parquet(feats_df, features_lake_path(league))
        (settings.data_dir / f"features_{league}.meta.json").write_text(
            json.dumps(meta, indent=1))
        log.info("features_written", league=league, rows=len(feats_df),
                 version=meta["feature_logic_version"], path=str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
