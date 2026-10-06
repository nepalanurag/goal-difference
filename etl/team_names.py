"""Team-name normalization.

Canonical names are fixed, human-readable spellings chosen per league
(generally the football-data.co.uk CSV spelling, which is the ongoing live
source). api-football, the FPL API, and the CSVs all use different
spellings; every variant is aliased here to the canonical form so a team's
identity is stable across seasons and sources.

Built from the actual 2023-2026 source data on 2026-10-06. Unknown names
fall back to difflib matching, then to the raw name with a loud warning
(validate.py catches anything outside the league's team set).
"""
from __future__ import annotations

import difflib

from .logging_setup import get_logger

log = get_logger(__name__)

# Canonical team names per league.
CANONICAL: dict[str, set[str]] = {
    "pl": {
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton",
        "Burnley", "Chelsea", "Coventry City", "Crystal Palace", "Everton",
        "Fulham", "Hull City", "Ipswich Town", "Leeds", "Leicester",
        "Liverpool", "Luton", "Man City", "Man United", "Newcastle",
        "Nott'm Forest", "Sheffield United", "Southampton", "Sunderland",
        "Tottenham", "West Ham", "Wolves",
    },
    "laliga": {
        "Alaves", "Almeria", "Ath Bilbao", "Ath Madrid", "Barcelona",
        "Betis", "Cadiz", "Celta", "Elche", "Espanyol", "Getafe", "Girona",
        "Granada", "La Coruna", "Las Palmas", "Leganes", "Levante",
        "Malaga", "Mallorca", "Osasuna", "Oviedo", "Rayo Vallecano",
        "Real Madrid", "Real Sociedad", "Santander", "Sevilla", "Valencia",
        "Valladolid", "Villarreal",
    },
    "bundesliga": {
        "Augsburg", "Bayern Munich", "Bochum", "Darmstadt", "Dortmund",
        "Ein Frankfurt", "Elversberg", "FC Koln", "Fortuna Dusseldorf",
        "Freiburg", "Hamburg", "Heidenheim", "Hoffenheim", "Holstein Kiel",
        "Leverkusen", "M'gladbach", "Mainz", "Paderborn", "RB Leipzig",
        "Schalke 04", "St Pauli", "Stuttgart", "Union Berlin",
        "Werder Bremen", "Wolfsburg",
    },
    "seriea": {
        "Atalanta", "Bologna", "Cagliari", "Como", "Cremonese", "Empoli",
        "Fiorentina", "Frosinone", "Genoa", "Inter", "Juventus", "Lazio",
        "Lecce", "Milan", "Monza", "Napoli", "Parma", "Pisa", "Roma",
        "Salernitana", "Sassuolo", "Torino", "Udinese", "Venezia", "Verona",
    },
    "ligue1": {
        "Angers", "Auxerre", "Brest", "Clermont", "Le Havre", "Le Mans",
        "Lens", "Lille", "Lorient", "Lyon", "Marseille", "Metz", "Monaco",
        "Montpellier", "Nantes", "Nice", "Paris FC", "Paris SG", "Reims",
        "Rennes", "St Etienne", "Strasbourg", "Toulouse", "Troyes",
    },
}

# api-football name -> canonical (from the actual 2023/2024 API responses).
API_ALIASES: dict[str, dict[str, str]] = {
    "pl": {
        "Manchester City": "Man City", "Manchester United": "Man United",
        "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'm Forest",
        "West Ham United": "West Ham", "Wolverhampton Wanderers": "Wolves",
        "Brighton & Hove Albion": "Brighton", "Tottenham Hotspur": "Tottenham",
        "Sheffield Utd": "Sheffield United", "Leeds United": "Leeds",
        "Leicester City": "Leicester", "Ipswich Town": "Ipswich Town",
        "Luton Town": "Luton",
    },
    "laliga": {
        "Athletic Club": "Ath Bilbao", "Atletico Madrid": "Ath Madrid",
        "Celta Vigo": "Celta", "Granada CF": "Granada",
        "Real Betis": "Betis",
    },
    "bundesliga": {
        "1. FC Köln": "FC Koln", "1899 Hoffenheim": "Hoffenheim",
        "Bayer Leverkusen": "Leverkusen", "Bayern München": "Bayern Munich",
        "Borussia Dortmund": "Dortmund",
        "Borussia Monchengladbach": "M'gladbach",
        "Eintracht Frankfurt": "Ein Frankfurt", "FC Augsburg": "Augsburg",
        "FC Heidenheim": "Heidenheim", "1. FC Heidenheim": "Heidenheim", "FSV Mainz 05": "Mainz",
        "SC Freiburg": "Freiburg", "SV Darmstadt 98": "Darmstadt",
        "VfB Stuttgart": "Stuttgart", "VfL Wolfsburg": "Wolfsburg",
        "Vfl Bochum": "Bochum",
    },
    "seriea": {
        "AC Milan": "Milan", "AS Roma": "Roma", "Hellas Verona": "Verona",
    },
    "ligue1": {
        "Paris Saint Germain": "Paris SG", "Paris Saint-Germain": "Paris SG",
        "AS Monaco": "Monaco",
        "Olympique Marseille": "Marseille", "Olympique Lyonnais": "Lyon",
        "RC Lens": "Lens", "LOSC Lille": "Lille", "OGC Nice": "Nice",
        "Stade Rennais": "Rennes", "RC Strasbourg": "Strasbourg",
        "Saint Etienne": "St Etienne", "AJ Auxerre": "Auxerre",
        "Stade Brestois 29": "Brest", "Stade de Reims": "Reims",
        "Montpellier HSC": "Montpellier", "FC Nantes": "Nantes",
        "Toulouse FC": "Toulouse", "FC Metz": "Metz",
        "Le Havre AC": "Le Havre", "SCO Angers": "Angers",
        "Clermont Foot": "Clermont", "FC Lorient": "Lorient",
    },
}

# football-data.co.uk CSV name -> canonical (from the actual 2025/2026 CSVs).
CSV_ALIASES: dict[str, dict[str, str]] = {
    "laliga": {
        "Espanol": "Espanyol", "Sociedad": "Real Sociedad",
        "Vallecano": "Rayo Vallecano",
    },
    "bundesliga": {
        # Legacy spellings from the first extract's canonical set.
        "B Munich": "Bayern Munich", "B Dortmund": "Dortmund",
        "B Monchengladbach": "M'gladbach", "Koln": "FC Koln",
        "Hamburger SV": "Hamburg", "1. FC Heidenheim": "Heidenheim",
        "Bayern M\u00fcnchen": "Bayern Munich",
        "Borussia M\u00f6nchengladbach": "M'gladbach",
    },
    "pl": {"Ipswich": "Ipswich Town"},
    "seriea": {},
    "ligue1": {},
}

# FPL team name -> canonical (Premier League only, 2026/27 bootstrap).
FPL_ALIASES: dict[str, str] = {
    "Man Utd": "Man United", "Spurs": "Tottenham",
}


def canonicalize(name: str, league: str, source: str = "api") -> str:
    """Map a source-specific team name to the canonical name."""
    name = (name or "").strip()
    known = CANONICAL.get(league, set())
    if name in known:
        return name
    if source == "fpl":
        alias_dicts = [FPL_ALIASES]
    elif source == "csv":
        alias_dicts = [CSV_ALIASES.get(league, {})]
    elif source == "any":
        alias_dicts = [CSV_ALIASES.get(league, {}), API_ALIASES.get(league, {}),
                       FPL_ALIASES]
    else:
        alias_dicts = [API_ALIASES.get(league, {})]
    for aliases in alias_dicts:
        if name in aliases:
            return aliases[name]
    matches = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.82)
    if matches:
        log.warning("fuzzy_team_match", raw=name, league=league, source=source,
                    matched=matches[0])
        return matches[0]
    log.error("unmapped_team_name", raw=name, league=league, source=source)
    return name
