"""Tests for etl.team_names: alias fallthrough across sources."""
from __future__ import annotations

from etl.team_names import canonicalize


def test_alias_fallthrough_across_sources():
    # "Ipswich" is defined in CSV_ALIASES but must work for API data too.
    assert canonicalize("Ipswich", "pl", "api") == "Ipswich Town"
    assert canonicalize("Ipswich", "pl", "csv") == "Ipswich Town"


def test_known_name_passthrough():
    assert canonicalize("Arsenal", "pl", "api") == "Arsenal"


def test_source_priority():
    # Source-specific mapping wins when defined.
    assert canonicalize("Manchester City", "pl", "api") == "Man City"


def test_bundesliga_promoted_2026_27():
    # Newly promoted teams use full official names from the API.
    assert canonicalize("SV Elversberg", "bundesliga", "api") == "Elversberg"
    assert canonicalize("FC Schalke 04", "bundesliga", "api") == "Schalke 04"
    assert canonicalize("SC Paderborn 07", "bundesliga", "api") == "Paderborn"


def test_bundesliga_prefix_variants():
    assert canonicalize("1. FC Union Berlin", "bundesliga", "api") == "Union Berlin"
    assert canonicalize("SV Werder Bremen", "bundesliga", "api") == "Werder Bremen"
    assert canonicalize("FC Bayern München", "bundesliga", "api") == "Bayern Munich"


def test_pl_2026_csv_short_names():
    assert canonicalize("Coventry", "pl", "csv") == "Coventry City"
    assert canonicalize("Hull", "pl", "csv") == "Hull City"
    assert canonicalize("Málaga", "laliga", "espn") == "Malaga"


def test_accent_folding_and_top5_espn_aliases():
    from etl.team_names import TOP5_TEAMS
    assert canonicalize("Cádiz", "laliga", "espn") == "Cadiz"
    assert canonicalize("Real Oviedo", "laliga", "espn") == "Oviedo"
    assert canonicalize("Saint-Étienne", "ligue1", "espn") == "St Etienne"
    assert canonicalize("PSG", "ligue1", "espn") == "Paris SG"
    assert "Arsenal" in TOP5_TEAMS and "AEK Athens" not in TOP5_TEAMS
