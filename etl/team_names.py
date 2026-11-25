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
import html
import unicodedata

from .logging_setup import get_logger

log = get_logger(__name__)


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFD", text)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()

# Canonical team names per league.
CANONICAL: dict[str, set[str]] = {
    "pl": {
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton",
        "Burnley", "Cardiff", "Chelsea", "Coventry City", "Crystal Palace",
        "Everton", "Fulham", "Huddersfield", "Hull City", "Ipswich Town",
        "Leeds", "Leicester", "Liverpool", "Luton", "Man City", "Man United",
        "Middlesbrough", "Newcastle", "Norwich", "Nott'm Forest",
        "Sheffield United", "Southampton", "Stoke", "Sunderland", "Swansea",
        "Tottenham", "Watford", "West Brom", "West Ham", "Wolves",
    },
    "laliga": {
        "Alaves", "Almeria", "Ath Bilbao", "Ath Madrid", "Barcelona",
        "Betis", "Cadiz", "Celta", "Eibar", "Elche", "Espanyol", "Getafe",
        "Girona", "Granada", "Huesca", "La Coruna", "Las Palmas", "Leganes",
        "Levante", "Malaga", "Mallorca", "Osasuna", "Oviedo",
        "Rayo Vallecano", "Real Madrid", "Real Sociedad", "Santander",
        "Sevilla", "Sp Gijon", "Valencia", "Valladolid", "Villarreal",
    },
    "bundesliga": {
        "Augsburg", "Bayern Munich", "Bielefeld", "Bochum", "Darmstadt",
        "Dortmund", "Ein Frankfurt", "Elversberg", "FC Koln",
        "Fortuna Dusseldorf", "Freiburg", "Greuther Furth", "Hamburg",
        "Hannover", "Heidenheim", "Hertha", "Hoffenheim", "Holstein Kiel",
        "Ingolstadt", "Leverkusen", "M'gladbach", "Mainz", "Nurnberg",
        "Paderborn", "RB Leipzig", "Schalke 04", "St Pauli", "Stuttgart",
        "Union Berlin", "Werder Bremen", "Wolfsburg",
    },
    "seriea": {
        "Atalanta", "Benevento", "Bologna", "Brescia", "Cagliari", "Carpi",
        "Chievo", "Como", "Cremonese", "Crotone", "Empoli", "Fiorentina",
        "Frosinone", "Genoa", "Inter", "Juventus", "Lazio", "Lecce", "Milan",
        "Monza", "Napoli", "Palermo", "Parma", "Pescara", "Pisa", "Roma",
        "Salernitana", "Sampdoria", "Sassuolo", "Spal", "Spezia", "Torino",
        "Udinese", "Venezia", "Verona",
    },
    "ligue1": {
        "Ajaccio", "Ajaccio GFCO", "Amiens", "Angers", "Auxerre", "Bastia",
        "Bordeaux", "Brest", "Caen", "Clermont", "Dijon", "Guingamp",
        "Le Havre", "Le Mans", "Lens", "Lille", "Lorient", "Lyon",
        "Marseille", "Metz", "Monaco", "Montpellier", "Nancy", "Nantes",
        "Nice", "Nimes", "Paris FC", "Paris SG", "Reims", "Rennes",
        "St Etienne", "Strasbourg", "Toulouse", "Troyes",
    },
}

TOP5_TEAMS: frozenset[str] = frozenset().union(*CANONICAL.values())


def team_league_map() -> dict[str, str]:
    """Map canonical team name -> league slug across the 5 domestic leagues."""
    return {team: lg for lg, teams in CANONICAL.items() for team in teams}


# api-football / Transfermarkt name -> canonical.
API_ALIASES: dict[str, dict[str, str]] = {
    "pl": {
        "Manchester City": "Man City", "Manchester United": "Man United",
        "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'm Forest",
        "West Ham United": "West Ham", "Wolverhampton Wanderers": "Wolves",
        "Brighton & Hove Albion": "Brighton", "Fulham FC": "Fulham",
        "Tottenham Hotspur": "Tottenham", "Sheffield Utd": "Sheffield United",
        "Leeds United": "Leeds", "Leicester City": "Leicester",
        "Ipswich Town": "Ipswich Town", "Luton Town": "Luton",
        "Cardiff City": "Cardiff", "Huddersfield Town": "Huddersfield",
        "Middlesbrough FC": "Middlesbrough", "Norwich City": "Norwich",
        "Stoke City": "Stoke", "Swansea City": "Swansea",
        "Watford FC": "Watford", "West Bromwich Albion": "West Brom",
    },
    "laliga": {
        "Athletic Club": "Ath Bilbao", "Athletic Bilbao": "Ath Bilbao",
        "Atletico Madrid": "Ath Madrid", "Atlético de Madrid": "Ath Madrid",
        "Celta Vigo": "Celta", "Celta de Vigo": "Celta",
        "Granada CF": "Granada", "Real Betis": "Betis",
        "Real Betis Balompié": "Betis", "Deportivo A Coruña": "La Coruna",
        "Elche CF": "Elche", "Getafe CF": "Getafe", "Málaga CF": "Malaga",
        "RCD Espanyol Barcelona": "Espanyol", "SD Eibar": "Eibar",
        "SD Huesca": "Huesca", "Sporting Gijón": "Sp Gijon",
    },
    "bundesliga": {
        "1. FC Köln": "FC Koln", "1.FC Köln": "FC Koln",
        "1899 Hoffenheim": "Hoffenheim", "TSG 1899 Hoffenheim": "Hoffenheim",
        "Bayer Leverkusen": "Leverkusen", "Bayer 04 Leverkusen": "Leverkusen",
        "Bayern München": "Bayern Munich", "FC Bayern München": "Bayern Munich",
        "FC Bayern Munich": "Bayern Munich", "Borussia Dortmund": "Dortmund",
        "Borussia Monchengladbach": "M'gladbach",
        "Borussia Mönchengladbach": "M'gladbach",
        "Eintracht Frankfurt": "Ein Frankfurt", "FC Augsburg": "Augsburg",
        "FC Heidenheim": "Heidenheim", "1. FC Heidenheim": "Heidenheim",
        "1. FC Heidenheim 1846": "Heidenheim", "FSV Mainz 05": "Mainz",
        "1. FSV Mainz 05": "Mainz", "1.FSV Mainz 05": "Mainz",
        "SC Freiburg": "Freiburg", "Sport-Club Freiburg": "Freiburg",
        "SV Darmstadt 98": "Darmstadt", "VfB Stuttgart": "Stuttgart",
        "VfL Wolfsburg": "Wolfsburg", "Vfl Bochum": "Bochum",
        "VfL Bochum": "Bochum", "1. FC Union Berlin": "Union Berlin",
        "1.FC Union Berlin": "Union Berlin", "FC Union Berlin": "Union Berlin",
        "SV Werder Bremen": "Werder Bremen", "FC St. Pauli": "St Pauli",
        "TSG Hoffenheim": "Hoffenheim", "SV Elversberg": "Elversberg",
        "SV 07 Elversberg": "Elversberg", "FC Schalke 04": "Schalke 04",
        "SC Paderborn 07": "Paderborn", "SC Paderborn": "Paderborn",
        "Arminia Bielefeld": "Bielefeld", "SpVgg Greuther Fürth": "Greuther Furth",
        "Hannover 96": "Hannover", "Hertha BSC": "Hertha",
        "Hertha Berlin": "Hertha", "FC Ingolstadt 04": "Ingolstadt",
        "1. FC Nürnberg": "Nurnberg",
    },
    "seriea": {
        "AC Milan": "Milan", "AC Monza": "Monza", "AS Roma": "Roma",
        "Hellas Verona": "Verona", "Bologna FC 1909": "Bologna",
        "Cagliari Calcio": "Cagliari", "Frosinone Calcio": "Frosinone",
        "Genoa CFC": "Genoa", "Parma Calcio 1913": "Parma",
        "SS Lazio": "Lazio", "SSC Napoli": "Napoli", "Torino FC": "Torino",
        "US Lecce": "Lecce", "Udinese Calcio": "Udinese", "SPAL": "Spal",
        "ChievoVerona": "Chievo", "Chievo Verona": "Chievo",
    },
    "ligue1": {
        "Paris Saint Germain": "Paris SG", "Paris Saint-Germain": "Paris SG",
        "AS Monaco": "Monaco", "Olympique Marseille": "Marseille",
        "Olympique Lyonnais": "Lyon", "Olympique Lyon": "Lyon",
        "RC Lens": "Lens", "LOSC Lille": "Lille", "OGC Nice": "Nice",
        "Stade Rennais": "Rennes", "Stade Rennais FC": "Rennes",
        "RC Strasbourg": "Strasbourg", "Saint Etienne": "St Etienne",
        "AJ Auxerre": "Auxerre", "Stade Brestois 29": "Brest",
        "Stade de Reims": "Reims", "Montpellier HSC": "Montpellier",
        "FC Nantes": "Nantes", "Toulouse FC": "Toulouse", "FC Metz": "Metz",
        "Le Havre AC": "Le Havre", "SCO Angers": "Angers",
        "Angers SCO": "Angers", "ESTAC Troyes": "Troyes",
        "Clermont Foot": "Clermont", "FC Lorient": "Lorient",
        "AC Ajaccio": "Ajaccio", "GFC Ajaccio": "Ajaccio GFCO",
        "Gazélec Ajaccio": "Ajaccio GFCO", "SC Bastia": "Bastia",
        "Girondins de Bordeaux": "Bordeaux", "SM Caen": "Caen",
        "EA Guingamp": "Guingamp", "AS Nancy": "Nancy", "Nîmes": "Nimes",
    },
}

# football-data.co.uk CSV name -> canonical.
CSV_ALIASES: dict[str, dict[str, str]] = {
    "laliga": {
        "Espanol": "Espanyol", "Sociedad": "Real Sociedad",
        "Vallecano": "Rayo Vallecano",
    },
    "bundesliga": {
        "B Munich": "Bayern Munich", "B Dortmund": "Dortmund",
        "B Monchengladbach": "M'gladbach", "Koln": "FC Koln",
        "Hamburger SV": "Hamburg", "1. FC Heidenheim": "Heidenheim",
        "Bayern M\u00fcnchen": "Bayern Munich",
        "Borussia M\u00f6nchengladbach": "M'gladbach",
    },
    "pl": {"Ipswich": "Ipswich Town", "Coventry": "Coventry City", "Hull": "Hull City"},
    "seriea": {},
    "ligue1": {},
}

# FPL team name -> canonical (Premier League only, 2026/27 bootstrap).
FPL_ALIASES: dict[str, str] = {
    "Man Utd": "Man United", "Spurs": "Tottenham",
}

# ESPN scoreboard & SportsGambler display name -> canonical.
ESPN_ALIASES: dict[str, dict[str, str]] = {
    "pl": {
        "Manchester City": "Man City", "Manchester United": "Man United",
        "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'm Forest",
        "West Ham United": "West Ham", "Wolverhampton Wanderers": "Wolves",
        "Brighton & Hove Albion": "Brighton", "Tottenham Hotspur": "Tottenham",
        "Leeds United": "Leeds", "Leicester City": "Leicester",
        "AFC Bournemouth": "Bournemouth", "Ipswich Town": "Ipswich Town",
        "Luton Town": "Luton", "Cardiff City": "Cardiff",
        "Huddersfield Town": "Huddersfield", "Norwich City": "Norwich",
        "Stoke City": "Stoke", "Swansea City": "Swansea",
        "West Bromwich Albion": "West Brom",
    },
    "laliga": {
        "Athletic Club": "Ath Bilbao", "Atlético Madrid": "Ath Madrid",
        "Atletico Madrid": "Ath Madrid", "Celta Vigo": "Celta",
        "Real Betis": "Betis", "Deportivo Alavés": "Alaves",
        "Deportivo Alaves": "Alaves", "Alavés": "Alaves",
        "Almería": "Almeria", "Cádiz": "Cadiz", "Leganés": "Leganes",
        "Racing Santander": "Santander", "Racing Club": "Santander",
        "Real Oviedo": "Oviedo", "Real Valladolid": "Valladolid",
        "Deportivo": "La Coruna", "Deportivo La Coruña": "La Coruna",
        "Deportivo La Coruna": "La Coruna", "Málaga": "Malaga",
        "SD Eibar": "Eibar", "SD Huesca": "Huesca", "Sporting Gijón": "Sp Gijon",
    },
    "bundesliga": {
        "Borussia Dortmund": "Dortmund", "Bayer Leverkusen": "Leverkusen",
        "Eintracht Frankfurt": "Ein Frankfurt", "Frankfurt": "Ein Frankfurt",
        "VfB Stuttgart": "Stuttgart",
        "Borussia Mönchengladbach": "M'gladbach",
        "Borussia Monchengladbach": "M'gladbach", "B. M'gladbach": "M'gladbach",
        "TSG Hoffenheim": "Hoffenheim", "1899 Hoffenheim": "Hoffenheim",
        "SC Freiburg": "Freiburg", "FSV Mainz 05": "Mainz",
        "Mainz 05": "Mainz", "FC Augsburg": "Augsburg",
        "VfL Wolfsburg": "Wolfsburg", "FC Heidenheim": "Heidenheim",
        "1. FC Heidenheim": "Heidenheim", "1. FC Köln": "FC Koln",
        "FC Cologne": "FC Koln", "St. Pauli": "St Pauli",
        "Hamburger SV": "Hamburg", "Hamburg SV": "Hamburg",
        "Bayern München": "Bayern Munich", "Bayern Munich": "Bayern Munich",
        "1. FC Union Berlin": "Union Berlin", "Union Berlin": "Union Berlin",
        "SC Paderborn 07": "Paderborn", "Paderborn": "Paderborn",
        "SV Elversberg": "Elversberg", "Elversberg": "Elversberg",
        "Arminia Bielefeld": "Bielefeld", "SpVgg Greuther Fürth": "Greuther Furth",
        "Greuther Fürth": "Greuther Furth", "Hannover 96": "Hannover",
        "Hertha Berlin": "Hertha", "Hertha BSC": "Hertha",
        "FC Ingolstadt 04": "Ingolstadt", "1. FC Nürnberg": "Nurnberg",
        "Nürnberg": "Nurnberg",
    },
    "seriea": {
        "AC Milan": "Milan", "AS Roma": "Roma", "Hellas Verona": "Verona",
        "Inter Milan": "Inter", "Internazionale": "Inter",
        "US Sassuolo": "Sassuolo", "Como 1907": "Como",
        "ChievoVerona": "Chievo", "Chievo Verona": "Chievo", "SPAL": "Spal",
    },
    "ligue1": {
        "Paris Saint-Germain": "Paris SG", "PSG": "Paris SG",
        "Olympique de Marseille": "Marseille", "Olympique Marseille": "Marseille",
        "Olympique Lyonnais": "Lyon", "AS Monaco": "Monaco",
        "LOSC Lille": "Lille", "RC Lens": "Lens",
        "OGC Nice": "Nice", "Stade Rennais": "Rennes",
        "RC Strasbourg": "Strasbourg", "RC Strasbourg Alsace": "Strasbourg",
        "AJ Auxerre": "Auxerre", "FC Nantes": "Nantes",
        "Toulouse FC": "Toulouse", "Stade Brestois 29": "Brest",
        "Le Havre AC": "Le Havre", "AS Saint-Étienne": "St Etienne",
        "AS Saint-Etienne": "St Etienne", "Saint-Étienne": "St Etienne",
        "Saint-Etienne": "St Etienne", "Montpellier HSC": "Montpellier",
        "FC Lorient": "Lorient", "Stade de Reims": "Reims",
        "AC Ajaccio": "Ajaccio", "GFC Ajaccio": "Ajaccio GFCO",
        "Gazélec Ajaccio": "Ajaccio GFCO", "SC Bastia": "Bastia",
        "Girondins de Bordeaux": "Bordeaux", "SM Caen": "Caen",
        "EA Guingamp": "Guingamp", "AS Nancy": "Nancy", "Nîmes": "Nimes",
    },
}


def canonicalize(name: str, league: str, source: str = "api") -> str:
    """Map a source-specific team name to the canonical name."""
    name = html.unescape((name or "")).replace("\u2019", "'").strip()
    known = CANONICAL.get(league, set())
    if name in known:
        return name
    folded = _fold(name)
    for k in known:
        if _fold(k) == folded:
            return k
    # Source-specific aliases first, then fall through to all sources.
    # A mapping defined for one source (e.g. "Ipswich" in CSV_ALIASES)
    # must work for the others too; siloed dicts drift and break validation.
    primary = {
        "fpl": FPL_ALIASES,
        "csv": CSV_ALIASES.get(league, {}),
        "espn": ESPN_ALIASES.get(league, {}),
    }.get(source, API_ALIASES.get(league, {}))
    if name in primary:
        return primary[name]
    for aliases in (CSV_ALIASES.get(league, {}), API_ALIASES.get(league, {}),
                    ESPN_ALIASES.get(league, {}), FPL_ALIASES):
        if aliases is not primary and name in aliases:
            return aliases[name]
    for aliases in (primary, CSV_ALIASES.get(league, {}), API_ALIASES.get(league, {}),
                    ESPN_ALIASES.get(league, {}), FPL_ALIASES):
        for k, v in aliases.items():
            if _fold(k) == folded:
                return v
    matches = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.82)
    if matches:
        log.warning("fuzzy_team_match", raw=name, league=league, source=source,
                    matched=matches[0])
        return matches[0]
    log.error("unmapped_team_name", raw=name, league=league, source=source)
    return name


def canonicalize_espn(name: str) -> str:
    """Map an ESPN scoreboard display name to the canonical team name.

    ESPN fixtures are cross-league, so every league's canonical set and
    ESPN aliases are tried. Names that match nothing (non-top-5 clubs)
    are returned unchanged; they simply never join against a league team.
    """
    name = html.unescape((name or "")).replace("\u2019", "'").strip()
    folded = _fold(name)
    for known in CANONICAL.values():
        if name in known:
            return name
        for k in known:
            if _fold(k) == folded:
                return k
    for aliases in ESPN_ALIASES.values():
        if name in aliases:
            return aliases[name]
    for aliases in API_ALIASES.values():
        if name in aliases:
            return aliases[name]
    for aliases in (*ESPN_ALIASES.values(), *API_ALIASES.values()):
        for k, v in aliases.items():
            if _fold(k) == folded:
                return v
    pool = sorted(TOP5_TEAMS)
    matches = difflib.get_close_matches(name, pool, n=1, cutoff=0.85)
    if matches:
        log.warning("fuzzy_espn_match", raw=name, matched=matches[0])
        return matches[0]
    log.info("espn_non_league_team", raw=name)
    return name
