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
