import pandas as pd
from etl.build_site import LeagueData, build_fixture
from etl.refresh import finished_hash


def test_prev_match_info_domestic_and_european():
    """Verify prev_match_info calculates athletic rest days and turnaround with match provenance."""
    ld = LeagueData("laliga")
    # Barcelona on 2026-10-25 has UCL match on 2026-10-20
    rest, turnaround, desc = ld.prev_match_info("Barcelona", "2026-10-25")
    assert turnaround == 5
    assert rest == 4  # max(0, 5 - 1)
    assert "2026-10-20" in desc
    assert "Paris SG" in desc

    # Real Madrid on 2026-10-25 has match on 2026-10-18 vs Sevilla
    rest_rm, turnaround_rm, desc_rm = ld.prev_match_info("Real Madrid", "2026-10-25")
    assert turnaround_rm == 7
    assert rest_rm == 6  # max(0, 7 - 1)
    assert "2026-10-18" in desc_rm
    assert "Sevilla" in desc_rm


def test_finished_hash_includes_scheduled_calendar(tmp_path, monkeypatch):
    """Finished hash must change if a scheduled fixture date changes, preventing false refresh no-ops."""
    from etl import config as cfg

    # Create dummy fixtures for leagues
    for lg in cfg.settings.league_order:
        rows = [
            {"fixture_id": f"{lg}_1", "date": "2026-08-10", "season": "2026",
             "home": "TeamA", "away": "TeamB", "home_goals": 1, "away_goals": 0, "status": "finished"},
            {"fixture_id": f"{lg}_2", "date": "2026-10-25", "season": "2026",
             "home": "TeamA", "away": "TeamB", "home_goals": None, "away_goals": None, "status": "scheduled"},
        ]
        pd.DataFrame(rows).to_csv(tmp_path / f"fixtures_{lg}.csv", index=False)

    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    h1 = finished_hash()

    # Modify scheduled fixture date (e.g. postponed by 1 day)
    df = pd.read_csv(tmp_path / f"fixtures_{cfg.settings.league_order[0]}.csv")
    df.loc[df["fixture_id"] == f"{cfg.settings.league_order[0]}_2", "date"] = "2026-10-26"
    df.to_csv(tmp_path / f"fixtures_{cfg.settings.league_order[0]}.csv", index=False)

    h2 = finished_hash()
    assert h1 != h2, "finished_hash must detect scheduled calendar updates"
