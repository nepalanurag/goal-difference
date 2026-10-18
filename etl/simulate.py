"""Simulate: 10,000 Monte Carlo season run-outs per league.

From the current table and the remaining fixtures, each run samples every
remaining fixture's scoreline from independent Poisson distributions
parameterized by the fitted model's expected goals (fixed seed), updates
points/goals dynamically, and records who finishes where. Tie-breaks follow
each league's actual rules:

  LaLiga, Serie A     points -> head-to-head points -> head-to-head GD
                      -> overall GD -> goals scored
                      (Serie A title playoff since 2022/23 is NOT simulated;
                      H2H decides it here, documented as a simplification.)
  Premier League,     points -> goal difference -> goals scored
  Bundesliga, Ligue 1

Outputs per-league data/odds_{league}.csv (title / top-4 / relegation odds)
and appends a date-stamped snapshot to data/odds_history.csv.

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

# Leagues whose first tie-breaker is head-to-head, not goal difference.
H2H_TIEBREAK_LEAGUES = {"laliga", "seriea"}


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
    teams = sorted(set(df["home"]) | set(df["away"]))
    table = pd.DataFrame([{
        "team": t, "played": played.get(t, 0), "points": pts.get(t, 0),
        "gf": gf.get(t, 0), "ga": ga.get(t, 0),
        "gd": gf.get(t, 0) - ga.get(t, 0),
    } for t in teams])
    return table


def real_h2h_matches(league: str, idx: dict[str, int]) -> list[tuple[int, int, int, int]]:
    """Finished live-season fixtures as (home_idx, away_idx, hg, ag)."""
    df = pd.read_csv(settings.data_dir / f"fixtures_{league}.csv",
                     dtype={"season": str})
    fin = df[(df["status"] == "finished") & (df["season"] == settings.live_season)]
    out = []
    for _, r in fin.iterrows():
        out.append((idx[r["home"]], idx[r["away"]],
                    int(r["home_goals"]), int(r["away_goals"])))
    return out


def _mini_table(group: list[int],
                matches: list[tuple[int, int, int, int]]) -> dict[int, tuple[int, int]]:
    """(h2h_points, h2h_gd) per team from matches within the group."""
    gset = set(group)
    hpts: dict[int, int] = {t: 0 for t in group}
    hgd: dict[int, int] = {t: 0 for t in group}
    for h, a, hg, ag in matches:
        if h in gset and a in gset:
            if hg > ag:
                hpts[h] += 3
            elif hg < ag:
                hpts[a] += 3
            else:
                hpts[h] += 1
                hpts[a] += 1
            hgd[h] += hg - ag
            hgd[a] += ag - hg
    return {t: (hpts[t], hgd[t]) for t in group}


def rank_teams(pts: np.ndarray, gf: np.ndarray, ga: np.ndarray,
               matches: list[tuple[int, int, int, int]],
               league: str) -> np.ndarray:
    """Final table order (best first) with league-specific tie-breaks."""
    gd = gf - ga
    # Primary sort by points desc; resolve tied groups below.
    order = np.argsort(-pts, kind="stable")
    pts_sorted = pts[order]
    # Find tied-on-points groups.
    result: list[int] = []
    i = 0
    n = len(order)
    use_h2h = league in H2H_TIEBREAK_LEAGUES
    while i < n:
        j = i + 1
        while j < n and pts_sorted[j] == pts_sorted[i]:
            j += 1
        group = order[i:j].tolist()
        if len(group) > 1 and use_h2h:
            mini = _mini_table(group, matches)
            group.sort(key=lambda t: (-mini[t][0], -mini[t][1],
                                      -gd[t], -gf[t], t))
        elif len(group) > 1:
            group.sort(key=lambda t: (-gd[t], -gf[t], t))
        result.extend(group)
        i = j
    return np.array(result, dtype=int)


def simulate_league(league: str) -> pd.DataFrame:
    n_teams = int(settings.leagues[league]["n_teams"])
    table = current_table(league)
    upcoming = predict_upcoming(league)
    if upcoming.empty:
        log.warning("no_upcoming_fixtures", league=league)

    teams = table["team"].tolist()
    idx = {t: i for i, t in enumerate(teams)}
    base_pts = table.set_index("team")["points"].to_numpy(dtype=float)
    base_gf = table.set_index("team")["gf"].to_numpy(dtype=float)
    base_ga = table.set_index("team")["ga"].to_numpy(dtype=float)
    real_matches = real_h2h_matches(league, idx)

    rng = np.random.default_rng(settings.simulation_seed)
    n = settings.simulation_runs

    xg_h = np.clip(upcoming["xg_home"].to_numpy(dtype=float), 0, None)
    xg_a = np.clip(upcoming["xg_away"].to_numpy(dtype=float), 0, None)
    home_idx = upcoming["home"].map(idx).to_numpy()
    away_idx = upcoming["away"].map(idx).to_numpy()

    titles = np.zeros(len(teams))
    top4 = np.zeros(len(teams))
    releg = np.zeros(len(teams))
    drop_zone = 3 if n_teams == 20 else 2

    for _ in range(n):
        pts = base_pts.copy()
        gf = base_gf.copy()
        ga = base_ga.copy()
        if len(upcoming):
            # Vectorized scoreline sampling from the fitted Poisson means.
            sh = rng.poisson(xg_h)
            sa = rng.poisson(xg_a)
            home_pts = np.where(sh > sa, 3.0, np.where(sh == sa, 1.0, 0.0))
            away_pts = np.where(sa > sh, 3.0, np.where(sh == sa, 1.0, 0.0))
            np.add.at(pts, home_idx, home_pts)
            np.add.at(pts, away_idx, away_pts)
            np.add.at(gf, home_idx, sh)
            np.add.at(ga, home_idx, sa)
            np.add.at(gf, away_idx, sa)
            np.add.at(ga, away_idx, sh)
            sim_matches = list(zip(home_idx.tolist(), away_idx.tolist(),
                                   sh.tolist(), sa.tolist()))
        else:
            sim_matches = []
        order = rank_teams(pts, gf, ga, real_matches + sim_matches, league)
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
