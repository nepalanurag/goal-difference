"""Simulate: 10,000 Monte Carlo season run-outs per league.

From the current table and the remaining fixtures, each run samples every
remaining fixture's outcome from the ensemble 1X2 probabilities (fixed seed),
adds the points, and records who finishes where. Outputs per-league
data/odds_{league}.csv (title / top-4 / relegation odds) and appends a
date-stamped snapshot to data/odds_history.csv.

Sanity: p_title, p_top4, p_relegation each sum to ~1 across teams
(top-4 sums to 4, relegation to the size of the drop zone).

Usage: python -m etl.simulate [--leagues ...]
"""
from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from .config import settings
from .fit import predict_upcoming
from .logging_setup import get_logger

log = get_logger(__name__)


def current_table(league: str) -> pd.DataFrame:
    """Live-season table (finished fixtures of settings.live_season only)."""
    df = pd.read_csv(settings.data_dir / f"fixtures_{league}.csv",
                     dtype={"season": str})
    fin = df[(df["status"] == "finished") & (df["season"] == settings.live_season)]
    pts: dict[str, int] = {}
    gf: dict[str, int] = {}
    ga: dict[str, int] = {}
    played: dict[str, int] = {}
    for _, r in fin.iterrows():
        for team, gf_k, ga_k in ((r["home"], r["home_goals"], r["away_goals"]),
                                 (r["away"], r["away_goals"], r["home_goals"])):
            gf_v, ga_v = int(gf_k), int(ga_k)
            played[team] = played.get(team, 0) + 1
            gf[team] = gf.get(team, 0) + gf_v
            ga[team] = ga.get(team, 0) + ga_v
            p = 3 if gf_v > ga_v else (1 if gf_v == ga_v else 0)
            pts[team] = pts.get(team, 0) + p
    live = df[df["season"] == settings.live_season]
    teams = sorted(set(live["home"]) | set(live["away"]))
    table = pd.DataFrame([{
        "team": t, "played": played.get(t, 0), "points": pts.get(t, 0),
        "gf": gf.get(t, 0), "ga": ga.get(t, 0),
        "gd": gf.get(t, 0) - ga.get(t, 0),
    } for t in teams])
    return table


def simulate_league(league: str) -> pd.DataFrame:
    n_teams = int(settings.leagues[league]["n_teams"])
    table = current_table(league)
    upcoming = predict_upcoming(league)
    if upcoming.empty:
        log.warning("no_upcoming_fixtures", league=league)

    rng = np.random.default_rng(settings.simulation_seed)
    n = settings.simulation_runs
    teams = table["team"].tolist()
    idx = {t: i for i, t in enumerate(teams)}
    base_pts = table.set_index("team")["points"].to_dict()
    base_gd = table.set_index("team")["gd"].to_dict()

    probs = upcoming[["p_away_ens", "p_draw_ens", "p_home_ens"]].to_numpy()
    home_idx = upcoming["home"].map(idx).to_numpy()
    away_idx = upcoming["away"].map(idx).to_numpy()

    titles = np.zeros(len(teams))
    top4 = np.zeros(len(teams))
    releg = np.zeros(len(teams))
    drop_zone = 3 if n_teams == 20 else 2

    for _ in range(n):
        pts = np.array([base_pts[t] for t in teams], dtype=float)
        gd = np.array([base_gd[t] for t in teams], dtype=float)
        if len(upcoming):
            draws = rng.random(len(upcoming))
            # outcome: 0=away, 1=draw, 2=home
            outcomes = np.where(draws < probs[:, 0], 0,
                                np.where(draws < probs[:, 0] + probs[:, 1], 1, 2))
            for o, hi, ai in zip(outcomes, home_idx, away_idx):
                if o == 2:
                    pts[hi] += 3
                elif o == 0:
                    pts[ai] += 3
                else:
                    pts[hi] += 1
                    pts[ai] += 1
        order = np.lexsort((-gd, -pts))  # points desc, then goal difference
        titles[order[0]] += 1
        top4[order[:4]] += 1
        releg[order[-drop_zone:]] += 1

    odds = pd.DataFrame({
        "team": teams,
        "p_title": titles / n,
        "p_top4": top4 / n,
        "p_relegation": releg / n,
        "sims": n,
        "sim_date": date.today().isoformat(),
    }).sort_values("p_title", ascending=False).reset_index(drop=True)
    assert abs(odds["p_title"].sum() - 1.0) < 1e-9, "title odds must sum to 1"
    assert abs(odds["p_top4"].sum() - 4.0) < 1e-9, "top-4 odds must sum to 4"
    assert abs(odds["p_relegation"].sum() - drop_zone) < 1e-9, "drop odds mismatch"
    return odds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monte Carlo season simulations.")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        choices=settings.league_order)
    args = parser.parse_args(argv)
    hist_path = settings.data_dir / "odds_history.csv"
    for league in args.leagues:
        odds = simulate_league(league)
        odds.to_csv(settings.data_dir / f"odds_{league}.csv", index=False)
        snap = odds[["team", "p_title", "p_top4", "p_relegation"]].copy()
        snap["date"] = date.today().isoformat()
        snap["league"] = league
        snap.to_csv(hist_path, mode="a", header=not hist_path.exists(), index=False)
        log.info("odds_written", league=league,
                 leader=f"{odds.iloc[0]['team']} {odds.iloc[0]['p_title']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
