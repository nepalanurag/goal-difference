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


def test_latest_team_features_includes_latest_finished_match(tmp_path, monkeypatch):
    rows = [
        {"fixture_id": "f1", "date": "2026-10-10", "season": "2026",
         "home": "Arsenal", "away": "Chelsea", "home_goals": 3, "away_goals": 0, "status": "finished"},
    ]
    pd.DataFrame(rows).to_csv(tmp_path / "fixtures_pl.csv", index=False)
    pd.DataFrame({"fixture_id": []}).to_csv(tmp_path / "features_pl.csv", index=False)
    (tmp_path / "h2h_pl.json").write_text("{}")
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    ld = LeagueData("pl")
    assert ld.latest_team_features("Arsenal")["gf_pg"] == 3.0
    assert ld.latest_team_features("Chelsea")["ga_pg"] == 3.0


def test_build_players_renders_risers_edge_and_bundesliga_ligue1(tmp_path, monkeypatch):
    from etl import build_site
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    (tmp_path / "players_pl.json").write_text(json.dumps({
        "players": [{"name": "Bukayo Saka", "web_name": "Saka", "team": "Arsenal", "position": "MID",
                     "form": 8.0, "total_points": 40, "goals": 4, "assists": 2, "minutes": 360,
                     "ict_index": 30.0, "now_cost": 10.0, "points_per_million": 4.0}],
        "in_form_xi": {"MID": [{"name": "Bukayo Saka", "team": "Arsenal", "form": 8.0}]},
        "risers": [{"name": "Bukayo Saka", "team": "Arsenal", "edge": 2.45}],
    }))
    (tmp_path / "player_rankings_official_bundesliga.json").write_text(json.dumps({
        "goals": [{"player": "Harry Kane", "club_id": "DFL-CLU-00000G", "value": 6}],
        "assists": [{"player": "Harry Kane", "club_id": "DFL-CLU-00000G", "value": 3}],
    }))
    (tmp_path / "player_rankings_official_ligue1.json").write_text(json.dumps({
        "scorers": [{"player": "Ousmane Dembele", "club": "Paris SG", "goals": 5, "assists": 2, "minutes": 400}],
        "assists": [],
    }))
    html = build_site.build_players({}, pd.DataFrame(), "2026-10-19")
    assert "+2.45" in html
    assert "Harry Kane" in html
    assert "Ousmane Dembele" in html


def test_team_news_ignores_departed_status_u():
    from etl.team_news import build_team_news_pl
    boot = {
        "teams": [{"id": 1, "name": "Arsenal"}],
        "elements": [
            {"id": 10, "first_name": "Ethan", "second_name": "Nwaneri", "team": 1,
             "element_type": 3, "status": "u", "minutes": 0,
             "chance_of_playing_this_round": 0,
             "news": "Has joined Borussia Dortmund on loan for the rest of the season"},
            {"id": 11, "first_name": "William", "second_name": "Saliba", "team": 1,
             "element_type": 2, "status": "i", "minutes": 450,
             "chance_of_playing_this_round": 0, "news": "Back injury"},
        ],
    }
    tn = build_team_news_pl(boot)["teams"]["Arsenal"]
    names = [p["player"] for p in tn["out"]]
    assert "William Saliba" in names
    assert "Ethan Nwaneri" not in names


def test_multi_source_team_news_parsers_and_merge():
    from etl.team_news import merge_multi_source_news, parse_sportsgambler, parse_transfermarkt

    sg_html = (
        '<div class="injury-block"><h3 class="injuries-title"><a href="/x">Barcelona</a></h3>'
        '<div class="inj-row"><span class="inj-type redcard"></span>'
        '<span class="inj-player">Pedri</span><span class="inj-position h-sm">M</span>'
        '<span class="inj-game h-sm">10</span><span class="inj-goals h-sm">2</span>'
        '<span class="inj-assist h-sm">3</span><span class="inj-info">Yellow cards</span>'
        '<span class="inj-return h-sm">-</span></div></div>'
    )
    sg = parse_sportsgambler(sg_html, "laliga")
    assert len(sg) == 1 and sg[0]["kind"] == "suspended" and sg[0]["team"] == "Barcelona"

    tm_html = (
        '<tr class="odd"><td><table><tr><td><td class="hauptlink">'
        '<a title="Lamine Yamal">Lamine Yamal</a></td></tr><tr><td>Right Winger</td></tr></table></td>'
        '<td class="zentriert no-border-rechts"><a title="FC Barcelona"></a></td>'
        '<td class="links">Ankle problems</td><td class="zentriert">29/11/2026</td>'
        '<td class="rechts">€220.00M</td></tr>'
    )
    tm = parse_transfermarkt(tm_html, "laliga")
    assert len(tm) == 1 and tm[0]["market_value_m"] == 220.0 and tm[0]["expected_return"] == "2026-11-29"

    merged = merge_multi_source_news("laliga", None, sg, tm, {})
    barca = merged["teams"]["Barcelona"]
    assert len(barca["out"]) == 2
    assert barca["drag_att"] > 0


def test_build_europe_filters_to_top5_ucl_uel(tmp_path, monkeypatch):
    from etl import build_site
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    (tmp_path / "european_fixtures.jsonl").write_text("\n".join([
        json.dumps({"fixture_id": "e1", "date": "2026-11-25", "competition": "UCL",
                    "home": "Arsenal", "away": "FC Porto", "home_goals": None, "away_goals": None, "status": "scheduled"}),
        json.dumps({"fixture_id": "e2", "date": "2026-11-25", "competition": "UEL",
                    "home": "Roma", "away": "Lazio", "home_goals": 2, "away_goals": 1, "status": "finished"}),
    ]) + "\n")
    html = build_site.build_europe({}, "2026-11-25")
    assert "Arsenal" in html and "Roma" in html and "Champions League" in html and "Europa League" in html
