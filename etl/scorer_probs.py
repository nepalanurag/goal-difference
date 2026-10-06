"""Anytime-scorer probabilities for upcoming fixtures (Phase 8.2).

Method (per the player-layer research notes):
  per90 = goals / (minutes / 90), shrunk toward a position prior:
      shrunk_rate = (goals + PRIOR_GOALS) / (minutes / 90 + PRIOR_90S)
  with PRIOR_GOALS = 2 and PRIOR_90S = 10. The prior is roughly "a generic
  attacker scores 0.2 goals per 90", so a player with few minutes regresses
  toward that instead of trusting a 1-goal-in-20-minutes sample.
  expected_minutes: minutes per appearance, capped at 90. Where the feed has
  no appearance count, a documented proxy is used (see _expected_minutes).
  team_lambda = xg_home / xg_away from predict_upcoming for the player's
  team; league_avg_lambda = mean of all xg values in that week's fixtures.
      X = shrunk_rate * (expected_minutes / 90) * (team_lambda / league_avg_lambda)
      P = 1 - exp(-X)

Penalty-taker uplift (PL only): X * 1.25 when the player's FPL
penalties_order is 1. The processed data/players_pl.json does not carry
set-piece notes, but the raw cache data/raw/fpl_bootstrap_static.json does,
so the uplift is read from there.

Bundesliga is excluded: its official feed publishes no minutes and no
positions, so per-90 rates cannot be computed. This is noted on the site.

Output: data/scorer_probs.csv with columns
player, team, fixture_id, home, away, date, per90, x_minutes, team_xg, prob.
per90 is the raw (unshrunk) rate; the shrunk rate is an internal input.

Usage: python -m etl.scorer_probs
"""
from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd

from .config import settings
from .logging_setup import get_logger
from .team_names import CANONICAL, canonicalize

log = get_logger(__name__)

# --- documented defaults ----------------------------------------------------
PRIOR_GOALS = 2.0     # goals in the empirical-Bayes prior
PRIOR_90S = 10.0      # 90-minute equivalents in the prior (~10 games)
PENALTY_UPLIFT = 1.25  # multiplier on X for designated penalty takers (PL)
MIN_MINUTES = 90      # players below this do not qualify
SCORER_CSV_COLS = ["player", "team", "fixture_id", "home", "away", "date",
                   "per90", "x_minutes", "team_xg", "prob"]

# Positions counted as attackers/midfielders per league. Ligue 1's feed is a
# scorers/assists ranking with no position field, so every listed player is
# eligible. Bundesliga has neither minutes nor positions: excluded.
ATT_POSITIONS: dict[str, set[str] | None] = {
    "pl": {"MID", "FWD"},
    "laliga": {"Delantero", "Centrocampista"},
    "seriea": {"Forward", "Midfielder"},
    "ligue1": None,
}

# DFL club id -> canonical team name. Derived 2026-10-06 by joining each
# club_id to the head coach in the official Firebase matchday lineups, then
# to the club via the published 2026-27 Bundesliga manager list. Spot check:
# Phillip Tietz (4 goals, DFL-CLU-000006) is listed as a Mainz 05 player in
# the same published source, and the map says Mainz.
BUNDESLIGA_CLUB_MAP = {
    "DFL-CLU-000002": "Hoffenheim",
    "DFL-CLU-000004": "M'gladbach",
    "DFL-CLU-000006": "Mainz",
    "DFL-CLU-000007": "Dortmund",
    "DFL-CLU-000008": "FC Koln",
    "DFL-CLU-000009": "Schalke 04",
    "DFL-CLU-00000A": "Freiburg",
    "DFL-CLU-00000B": "Leverkusen",
    "DFL-CLU-00000C": "Hamburg",
    "DFL-CLU-00000D": "Stuttgart",
    "DFL-CLU-00000E": "Werder Bremen",
    "DFL-CLU-00000F": "Ein Frankfurt",
    "DFL-CLU-00000G": "Bayern Munich",
    "DFL-CLU-00000L": "Paderborn",
    "DFL-CLU-00000V": "Union Berlin",
    "DFL-CLU-000010": "Augsburg",
    "DFL-CLU-000017": "RB Leipzig",
    "DFL-CLU-000N6L": "Elversberg",
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


# Official LaLiga backend names are full legal names ("Valencia Club de
# Fútbol SAD"); map them to the canonical short names used on the site.
_LALIGA_RULES: list[tuple[str, str]] = [
    ("atletico de madrid", "Ath Madrid"),
    ("athletic", "Ath Bilbao"),
    ("espanyol", "Espanyol"),
    ("barcelona", "Barcelona"),
    ("real madrid", "Real Madrid"),
    ("betis", "Betis"),
    ("cadiz", "Cadiz"),
    ("celta", "Celta"),
    ("coruna", "La Coruna"),
    ("alaves", "Alaves"),
    ("elche", "Elche"),
    ("getafe", "Getafe"),
    ("girona", "Girona"),
    ("granada", "Granada"),
    ("las palmas", "Las Palmas"),
    ("leganes", "Leganes"),
    ("levante", "Levante"),
    ("mallorca", "Mallorca"),
    ("malaga", "Malaga"),
    ("osasuna", "Osasuna"),
    ("oviedo", "Oviedo"),
    ("rayo", "Rayo Vallecano"),
    ("real sociedad", "Real Sociedad"),
    ("racing", "Santander"),
    ("sevilla", "Sevilla"),
    ("valencia", "Valencia"),
    ("valladolid", "Valladolid"),
    ("villarreal", "Villarreal"),
    ("almeria", "Almeria"),
]


def normalize_laliga_team(name: str | None) -> str | None:
    """Map an official LaLiga backend team name to the canonical name.

    Returns None for reserve sides and clubs outside the league's team set.
    """
    if not name:
        return None
    n = _strip_accents(name).lower()
    if "fortuna" in n or re.search(r"\bb$", n):
        return None  # reserve sides (e.g. "R. Sociedad B", "RC Celta Fortuna")
    for sub, canon in _LALIGA_RULES:
        if sub in n:
            return canon
    return None


# --- pure math ----------------------------------------------------------------

def shrunk_per90(goals: float, minutes: float,
                 prior_goals: float = PRIOR_GOALS,
                 prior_90s: float = PRIOR_90S) -> float:
    """Goals per 90 shrunk toward the position prior (empirical Bayes)."""
    n90 = (minutes or 0) / 90.0
    return (goals + prior_goals) / (n90 + prior_90s)


def scorer_prob(shrunk_rate: float, x_minutes: float, team_xg: float,
                league_avg_xg: float, penalty: bool = False) -> float:
    """Anytime-scorer probability: P = 1 - exp(-X)."""
    x = shrunk_rate * (x_minutes / 90.0) * (team_xg / league_avg_xg)
    if penalty:
        x *= PENALTY_UPLIFT
    return 1.0 - math.exp(-x)


# --- player pools ---------------------------------------------------------------

def _pl_pool() -> list[dict]:
    """PL players from players_pl.json plus starts/penalty data from the raw
    FPL bootstrap (matched on web_name + canonical team)."""
    d = settings.data_dir
    pl = json.loads((d / "players_pl.json").read_text())
    raw_path = d / "raw" / "fpl_bootstrap_static.json"
    extra: dict[tuple[str, str], dict] = {}
    if raw_path.exists():
        boot = json.loads(raw_path.read_text())
        teams = {t["id"]: canonicalize(t["name"], "pl", source="fpl")
                 for t in boot.get("teams", [])}
        for el in boot.get("elements", []):
            extra[(el.get("web_name"), teams.get(el.get("team")))] = el
    else:
        log.warning("fpl_bootstrap_missing", path=str(raw_path))
    pool = []
    for p in pl.get("players", []):
        if p.get("position") not in (ATT_POSITIONS["pl"] or set()):
            continue
        if (p.get("minutes") or 0) < MIN_MINUTES:
            continue
        el = extra.get((p.get("web_name"), p.get("team")), {})
        pool.append({
            "name": p.get("web_name") or p.get("name"),
            "team": p.get("team"),
            "goals": p.get("goals") or 0,
            "minutes": p.get("minutes") or 0,
            "appearances": None,
            "starts": el.get("starts"),
            "penalty": (el.get("penalties_order") == 1),
            "_league": "pl",
        })
    log.info("pl_pool", n=len(pool))
    return pool


def _expected_minutes(p: dict) -> float:
    """Minutes per appearance, capped at 90.

    Uses the feed's appearance count where available. PL has no appearance
    count: starters get minutes-per-start; non-starters are capped at 45
    (bench role). Ligue 1 has neither: minutes per ceil(minutes/90) is an
    upper-bound proxy, documented as such.
    """
    minutes = p.get("minutes") or 0
    apps = p.get("appearances")
    if apps:
        return min(90.0, minutes / max(apps, 1))
    starts = p.get("starts")
    if starts:
        return min(90.0, minutes / max(starts, 1))
    if p.get("_league") == "pl":
        return min(45.0, float(minutes))  # PL non-starter: bench role
    n = max(1, math.ceil(minutes / 90.0))
    return min(90.0, minutes / n)


def _laliga_pool() -> list[dict]:
    d = json.loads((settings.data_dir /
                    "player_rankings_official_laliga.json").read_text())
    pool = []
    for p in d.get("players", []):
        if p.get("position") not in (ATT_POSITIONS["laliga"] or set()):
            continue
        if (p.get("minutes") or 0) < MIN_MINUTES:
            continue
        pool.append({
            "name": p.get("nickname") or p.get("name"),
            "team": normalize_laliga_team(p.get("team")),
            "goals": p.get("goals") or 0,
            "minutes": p.get("minutes") or 0,
            "appearances": p.get("appearances"),
            "starts": p.get("starts"),
            "penalty": False,
            "_league": "laliga",
        })
    return pool


def _seriea_pool() -> list[dict]:
    d = json.loads((settings.data_dir /
                    "player_rankings_official_seriea.json").read_text())
    pool = []
    for p in d.get("players", []):
        if p.get("position") not in (ATT_POSITIONS["seriea"] or set()):
            continue
        if (p.get("minutes") or 0) < MIN_MINUTES:
            continue
        team = canonicalize(p.get("team") or "", "seriea", source="any")
        if team not in CANONICAL["seriea"]:
            team = p.get("team_short")
        pool.append({
            "name": p.get("name"),
            "team": team,
            "goals": p.get("goals") or 0,
            "minutes": p.get("minutes") or 0,
            "appearances": p.get("appearances"),
            "starts": None,
            "penalty": False,
            "_league": "seriea",
        })
    return pool


def _ligue1_pool() -> list[dict]:
    d = json.loads((settings.data_dir /
                    "player_rankings_official_ligue1.json").read_text())
    by_name: dict[str, dict] = {}
    for e in d.get("scorers", []) + d.get("assists", []):
        key = e.get("player")
        cur = by_name.setdefault(key, {"goals": 0, "assists": 0,
                                       "minutes": 0, "club": e.get("club")})
        cur["goals"] = max(cur["goals"], e.get("goals") or 0)
        cur["assists"] = max(cur["assists"], e.get("assists") or 0)
        cur["minutes"] = max(cur["minutes"], e.get("minutes") or 0)
    pool = []
    for name, e in by_name.items():
        if (e["minutes"] or 0) < MIN_MINUTES:
            continue
        pool.append({
            "name": name,
            "team": e["club"],
            "goals": e["goals"],
            "minutes": e["minutes"],
            "appearances": None,
            "starts": None,
            "penalty": False,
            "_league": "ligue1",
        })
    return pool


def load_player_pool(league: str) -> list[dict]:
    """Eligible attackers/midfielders (90+ mins) for a league, or [] when the
    feed cannot support per-90 rates (Bundesliga)."""
    if league == "pl":
        return _pl_pool()
    if league == "laliga":
        return _laliga_pool()
    if league == "seriea":
        return _seriea_pool()
    if league == "ligue1":
        return _ligue1_pool()
    if league == "bundesliga":
        log.info("bundesliga_scorers_skipped",
                 reason="official feed has no minutes or positions")
    return []


# --- main computation -----------------------------------------------------------

def _this_week(pred: pd.DataFrame) -> pd.DataFrame:
    first = pd.to_datetime(pred["date"]).min()
    return pred[pd.to_datetime(pred["date"]) <= first + pd.Timedelta(days=4)]


def compute_scorer_probs(preds: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Anytime-scorer probabilities for this week's fixtures.

    preds: league -> predict_upcoming output. Returns one row per
    player-fixture with the columns in SCORER_CSV_COLS.
    """
    rows = []
    for league, pred in preds.items():
        if pred is None or pred.empty:
            continue
        pool = load_player_pool(league)
        if not pool:
            continue
        week = _this_week(pred)
        lams = pd.concat([week["xg_home"], week["xg_away"]]).astype(float)
        league_avg = float(lams.mean()) if len(lams) else 1.0
        by_team: dict[str, list[dict]] = {}
        for p in pool:
            if p["team"]:
                by_team.setdefault(p["team"], []).append(p)
        for _, r in week.iterrows():
            for team, team_xg in ((r.home, r.xg_home), (r.away, r.xg_away)):
                for p in by_team.get(team, []):
                    minutes = p["minutes"]
                    rate = shrunk_per90(p["goals"], minutes)
                    x_min = _expected_minutes(p)
                    prob = scorer_prob(rate, x_min, float(team_xg),
                                       league_avg, penalty=p["penalty"])
                    rows.append({
                        "player": p["name"],
                        "team": team,
                        "fixture_id": r.fixture_id,
                        "home": r.home,
                        "away": r.away,
                        "date": r.date,
                        "per90": round(p["goals"] / (minutes / 90.0), 3),
                        "x_minutes": round(x_min, 1),
                        "team_xg": round(float(team_xg), 2),
                        "prob": round(prob, 4),
                    })
    df = pd.DataFrame(rows, columns=SCORER_CSV_COLS)
    if not df.empty:
        df = df.sort_values("prob", ascending=False).reset_index(drop=True)
    return df


def main() -> int:
    from .fit import predict_upcoming
    preds = {}
    for league in settings.league_order:
        try:
            preds[league] = predict_upcoming(league)
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            log.warning("predictions_failed", league=league,
                        error=str(exc)[:160])
            preds[league] = pd.DataFrame()
    df = compute_scorer_probs(preds)
    out = settings.data_dir / "scorer_probs.csv"
    df.to_csv(out, index=False)
    log.info("scorer_probs_written", rows=len(df), path=str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
