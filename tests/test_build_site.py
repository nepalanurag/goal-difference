import json
import pandas as pd
from etl import config as cfg
from etl.build_site import LeagueData
from etl.refresh import finished_hash


def test_prev_match_info_domestic_and_european(tmp_path, monkeypatch):
    """Verify prev_match_info calculates athletic rest days and turnaround with match provenance."""
    fixtures_rows = [
        {"fixture_id": "f1", "date": "2026-10-17", "season": "2026",
         "home": "Betis", "away": "Barcelona", "home_goals": 2, "away_goals": 5, "status": "finished"},
        {"fixture_id": "f2", "date": "2026-10-18", "season": "2026",
         "home": "Real Madrid", "away": "Sevilla", "home_goals": 4, "away_goals": 1, "status": "finished"},
        {"fixture_id": "f3", "date": "2026-10-25", "season": "2026",
         "home": "Barcelona", "away": "Real Madrid", "home_goals": None, "away_goals": None, "status": "scheduled"},
    ]
    pd.DataFrame(fixtures_rows).to_csv(tmp_path / "fixtures_laliga.csv", index=False)
    pd.DataFrame({"fixture_id": []}).to_csv(tmp_path / "features_laliga.csv", index=False)
    (tmp_path / "h2h_laliga.json").write_text("{}")

    euro_rows = [
        {"fixture_id": "ucl_1", "date": "2026-10-20", "competition": "UCL",
         "home": "Paris SG", "away": "Barcelona", "home_goals": None, "away_goals": None, "status": "scheduled"}
    ]
    (tmp_path / "european_fixtures.jsonl").write_text(
        "\n".join(json.dumps(r) for r in euro_rows) + "\n"
    )

    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    ld = LeagueData("laliga")

    # Barcelona on 2026-10-25 has UCL match on 2026-10-20 -> 5d turnaround, 4d rest
    rest, turnaround, desc = ld.prev_match_info("Barcelona", "2026-10-25")
    assert turnaround == 5
    assert rest == 4  # max(0, 5 - 1)
    assert "2026-10-20" in desc
    assert "Paris SG" in desc

    # Real Madrid on 2026-10-25 has match on 2026-10-18 vs Sevilla -> 7d turnaround, 6d rest
    rest_rm, turnaround_rm, desc_rm = ld.prev_match_info("Real Madrid", "2026-10-25")
    assert turnaround_rm == 7
    assert rest_rm == 6  # max(0, 7 - 1)
    assert "2026-10-18" in desc_rm
    assert "Sevilla" in desc_rm


def test_finished_hash_includes_scheduled_calendar(tmp_path, monkeypatch):
    """Finished hash must change if a scheduled fixture date changes, preventing false refresh no-ops."""
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

    df = pd.read_csv(tmp_path / f"fixtures_{cfg.settings.league_order[0]}.csv")
    df.loc[df["fixture_id"] == f"{cfg.settings.league_order[0]}_2", "date"] = "2026-10-26"
    df.to_csv(tmp_path / f"fixtures_{cfg.settings.league_order[0]}.csv", index=False)

    h2 = finished_hash()
    assert h1 != h2, "finished_hash must detect scheduled calendar updates"
