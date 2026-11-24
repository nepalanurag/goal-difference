"""Extract: pull fixtures per league/season, normalize, cache raw.

Sources, in priority order:
  2023/24 + 2024/25  api-football (free tier) -> CSV fallback on any failure
  2025/26            football-data.co.uk CSV only (api-football blocks it)
  2026/27 (live)     FPL API for the Premier League (CSV backup);
                     football-data.co.uk current-season CSVs for the rest

European fixtures: ESPN's hidden scoreboard API (free, no key),
accumulated into data/european_fixtures.jsonl (deduped by fixture id;
scheduled rows are upgraded in place once finished).

Every raw response is cached under data/raw/ before parsing. Output:
data/fixtures_{league}.csv with the contract in etl/README.md.

Usage:
    python -m etl.extract [--leagues pl laliga] [--seasons 2023 2024]
                          [--prefer-csv] [--skip-europe]
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .api_football import api_get
from .config import settings
from .logging_setup import get_logger
from .storage import raw_lake_path, write_parquet
from .team_names import canonicalize

log = get_logger(__name__)

CSV_BASE = "https://www.football-data.co.uk/mmz4281"
CSV_SEASON_CODE = {"2023": "2324", "2024": "2425", "2025": "2526", "2026": "2627"}

# Extra stat columns carried through from the CSVs (nullable for API rows).
STAT_COLS = ["hs", "as_", "hst", "ast", "hf", "af", "hy", "ay", "hr", "ar"]
CSV_STAT_MAP = {
    "HS": "hs", "AS": "as_", "HST": "hst", "AST": "ast",
    "HF": "hf", "AF": "af", "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar",
}

OUTPUT_COLS = [
    "fixture_id", "date", "season", "league", "home", "away",
    "home_goals", "away_goals", "status", "provenance", "api_fixture_id",
] + STAT_COLS


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def cache_raw(name: str, payload: bytes | str) -> Path:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    path = settings.raw_dir / name
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    path.write_bytes(data)
    return path


def cached(name: str) -> Path | None:
    path = settings.raw_dir / name
    return path if path.exists() else None


# ---------------------------------------------------------------- API source
def fetch_api_fixtures(league: str, season: str) -> pd.DataFrame:
    """Fixtures for one league/season from api-football. Raises on failure."""
    api_id = settings.leagues[league]["api_id"]
    data = api_get("/fixtures", {"league": api_id, "season": int(season)})
    if data.get("errors"):
        raise RuntimeError(f"api-football errors: {data['errors']}")
    cache_raw(f"api_fixtures_{league}_{season}.json", json.dumps(data["response"]))
    rows = []
    for fx in data["response"]:
        # League matches only: skip relegation playoffs and similar extras.
        if not fx["league"]["round"].startswith("Regular Season"):
            continue
        status = fx["fixture"]["status"]["short"]
        finished = status == "FT"
        kickoff = fx["fixture"]["date"][:10]
        home = canonicalize(fx["teams"]["home"]["name"], league, "api")
        away = canonicalize(fx["teams"]["away"]["name"], league, "api")
        fid = slugify(f"{league}-{season}-{kickoff}-{home}-v-{away}")
        rows.append({
            "fixture_id": fid,
            "date": kickoff,
            "season": season,
            "league": league,
            "home": home,
            "away": away,
            "home_goals": fx["goals"]["home"] if finished else None,
            "away_goals": fx["goals"]["away"] if finished else None,
            "status": "finished" if finished else "scheduled",
            "provenance": "api_football",
            "api_fixture_id": fx["fixture"]["id"],
            **{c: None for c in STAT_COLS},
        })
    log.info("api_fixtures", league=league, season=season, n=len(rows))
    return pd.DataFrame(rows, columns=OUTPUT_COLS)


# ---------------------------------------------------------------- CSV source
def fetch_csv(league: str, season: str) -> pd.DataFrame:
    """football-data.co.uk CSV for one league/season.

    Always re-downloads; falls back to the cached copy on failure.
    (The old code only downloaded once and served the stale cache forever.)
    """
    csv_code = settings.leagues[league]["csv_code"]
    season_code = CSV_SEASON_CODE[season]
    url = f"{CSV_BASE}/{season_code}/{csv_code}.csv"
    cache_name = f"csv_{league}_{season}.csv"
    path = cached(cache_name)
    provenance = "csv_cached"

    # Completed historical seasons never change; reuse local cache directly
    if season in settings.historical_seasons and path is not None:
        pass
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            # Strip UTF-8 BOM; the site redirects (handled by urlopen).
            text = raw.decode("utf-8-sig")
            cache_raw(cache_name, text)
            path = settings.raw_dir / cache_name
            provenance = "csv_download"
        except Exception as exc:
            if path is None:
                raise RuntimeError(f"CSV download failed for {url}: {exc}") from exc
            log.warning("csv_download_failed_using_cache", league=league,
                        season=season, error=str(exc)[:200])
    df = pd.read_csv(path, encoding="utf-8-sig")
    rows = []
    for _, r in df.iterrows():
        try:
            dt = pd.to_datetime(r["Date"], dayfirst=True).date().isoformat()
        except Exception:
            continue
        fthg, ftag = r.get("FTHG"), r.get("FTAG")
        finished = pd.notna(fthg) and pd.notna(ftag)
        home = canonicalize(str(r["HomeTeam"]), league, "csv")
        away = canonicalize(str(r["AwayTeam"]), league, "csv")
        fid = slugify(f"{league}-{season}-{dt}-{home}-v-{away}")
        row = {
            "fixture_id": fid,
            "date": dt,
            "season": season,
            "league": league,
            "home": home,
            "away": away,
            "home_goals": int(fthg) if finished else None,
            "away_goals": int(ftag) if finished else None,
            "status": "finished" if finished else "scheduled",
            "provenance": provenance,
            "api_fixture_id": None,
        }
        for csv_col, out_col in CSV_STAT_MAP.items():
            val = r.get(csv_col)
            row[out_col] = None if pd.isna(val) else float(val)
        rows.append(row)
    log.info("csv_fixtures", league=league, season=season, n=len(rows),
             provenance=provenance)
    return pd.DataFrame(rows, columns=OUTPUT_COLS)


# ---------------------------------------------------------------- FPL source
FPL_TEAMS_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"


def _fpl_get(url: str, cache_name: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    cache_raw(cache_name, raw)
    return json.loads(raw)


def fetch_fpl() -> pd.DataFrame:
    """Live Premier League season from the FPL API (no key, unofficial)."""
    league, season = "pl", settings.live_season
    try:
        boot = _fpl_get(FPL_TEAMS_URL, "fpl_bootstrap_static.json")
        fixtures = _fpl_get(FPL_FIXTURES_URL, "fpl_fixtures.json")
    except Exception as exc:
        raise RuntimeError(f"FPL fetch failed: {exc}") from exc
    team_name = {t["id"]: canonicalize(t["name"], "pl", "fpl") for t in boot["teams"]}
    rows = []
    now_utc = datetime.now(timezone.utc)
    for fx in fixtures:
        # FPL flips `finished` only after bonus points are calculated,
        # which can lag the final whistle by hours. Also treat a fixture
        # as done if it has final scores and kicked off 3+ hours ago.
        finished = bool(fx.get("finished"))
        if not finished:
            hs, aws = fx.get("team_h_score"), fx.get("team_a_score")
            ko = fx.get("kickoff_time", "")
            try:
                ko_dt = datetime.fromisoformat(ko.replace("Z", "+00:00"))
            except ValueError:
                ko_dt = None
            if (hs is not None and aws is not None and ko_dt is not None
                    and (now_utc - ko_dt).total_seconds() > 3 * 3600):
                finished = True
        kickoff = fx.get("kickoff_time", "")[:10]
        home = team_name[fx["team_h"]]
        away = team_name[fx["team_a"]]
        fid = slugify(f"pl-{season}-{kickoff}-{home}-v-{away}")
        rows.append({
            "fixture_id": fid,
            "date": kickoff,
            "season": season,
            "league": league,
            "home": home,
            "away": away,
            "home_goals": fx.get("team_h_score") if finished else None,
            "away_goals": fx.get("team_a_score") if finished else None,
            "status": "finished" if finished else "scheduled",
            "provenance": "fpl_api",
            "api_fixture_id": fx["id"],
            **{c: None for c in STAT_COLS},
        })
    log.info("fpl_fixtures", n=len(rows),
             finished=sum(1 for r in rows if r["status"] == "finished"))
    return pd.DataFrame(rows, columns=OUTPUT_COLS)


# ---------------------------------------------------------------- ESPN source
# Live-season results for non-PL leagues via ESPN's public scoreboard API.
# football-data.co.uk CSVs lag by weeks; ESPN has full-time scores same-day.
ESPN_LEAGUES = ("laliga", "bundesliga", "seriea", "ligue1")
ESPN_SEASON_START = f"{settings.live_season}-08-01"


def _merge_csv_stats(live_df: pd.DataFrame, csv_df: pd.DataFrame) -> pd.DataFrame:
    """Backfill shot/foul/card STAT_COLS from CSV onto matching live rows."""
    if live_df.empty or csv_df.empty:
        return live_df
    fin_csv = csv_df[csv_df["status"] == "finished"]
    by_pair = {(r["home"], r["away"]): r for _, r in fin_csv.iterrows()}
    out = live_df.copy()
    for idx, r in out.iterrows():
        if r["status"] != "finished":
            continue
        match = by_pair.get((r["home"], r["away"]))
        if match is None:
            continue
        for c in STAT_COLS:
            if pd.isna(r[c]) and pd.notna(match[c]):
                out.at[idx, c] = match[c]
    return out


def fetch_espn_results(league: str, season: str) -> pd.DataFrame:
    """Live-season fixtures+results for a league via ESPN scoreboard.

    Fetches every date from season start to today. Returns OUTPUT_COLS
    DataFrame with provenance="espn". Raises on total failure.
    """
    from .uefa import fetch_espn_league
    today = date.today().isoformat()
    rows = fetch_espn_league(league, ESPN_SEASON_START, today)
    if not rows:
        raise RuntimeError(f"ESPN returned no fixtures for {league}")
    out = []
    for r in rows:
        finished = r["status"] == "finished"
        out.append({
            "fixture_id": r["fixture_id"],
            "date": r["date"],
            "season": season,
            "league": league,
            "home": canonicalize(r["home"], league, "espn"),
            "away": canonicalize(r["away"], league, "espn"),
            "home_goals": r["home_goals"] if finished else None,
            "away_goals": r["away_goals"] if finished else None,
            "status": r["status"],
            "provenance": "espn",
            "api_fixture_id": None,
            **{c: None for c in STAT_COLS},
        })
    log.info("espn_results", league=league, season=season, n=len(out),
             finished=sum(1 for r in out if r["status"] == "finished"))
    return pd.DataFrame(out, columns=OUTPUT_COLS)


# ---------------------------------------------------------------- per-season
def extract_league_season(league: str, season: str, prefer_csv: bool) -> pd.DataFrame:
    if season in settings.historical_seasons and not prefer_csv:
        try:
            return fetch_api_fixtures(league, season)
        except Exception as exc:
            log.warning("api_failed_falling_back_to_csv", league=league,
                        season=season, error=str(exc)[:200])
    if season == settings.live_season and not prefer_csv:
        live_df = None
        if league == "pl":
            try:
                live_df = fetch_fpl()
            except Exception as exc:
                log.warning("fpl_failed_falling_back_to_csv", error=str(exc)[:200])
        elif league in ESPN_LEAGUES:
            try:
                live_df = fetch_espn_results(league, season)
            except Exception as exc:
                log.warning("espn_failed_falling_back_to_csv", league=league,
                            season=season, error=str(exc)[:200])
        if live_df is not None:
            try:
                csv_df = fetch_csv(league, season)
                live_df = _merge_csv_stats(live_df, csv_df)
            except Exception as exc:
                log.warning("live_csv_backfill_skipped", league=league,
                            season=season, error=str(exc)[:200])
            return live_df
    # CSV path: fallback when APIs fail.
    try:
        return fetch_csv(league, season)
    except Exception as exc:
        raise RuntimeError(
            f"Both API and CSV failed for {league} {season}: {exc}") from exc


def extract_league(league: str, seasons: list[str], prefer_csv: bool) -> pd.DataFrame:
    frames = [extract_league_season(league, s, prefer_csv) for s in seasons]
    frames = [f for f in frames if not f.empty]
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["fixture_id"], keep="first")
    df = df.sort_values("date").reset_index(drop=True)
    return df


# ---------------------------------------------------------------- European
def accumulate_european(dates: list[str]) -> Path:
    """Accumulate UEFA fixtures via ESPN's scoreboard API (free, no key).

    Fetches the full date range spanned by `dates` and appends new rows to
    data/european_fixtures.jsonl, deduplicated by fixture_id. Rows first
    seen as scheduled are upgraded in place once the finished result lands,
    so stale scheduled rows never linger.
    """
    from .uefa import fetch_espn_uefa
    out = settings.data_dir / "european_fixtures.jsonl"
    lines: list[str] = []
    index: dict[str, int] = {}
    if out.exists():
        with open(out) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    fx = json.loads(line)
                    index[fx["fixture_id"]] = len(lines)
                    lines.append(line)
                except (json.JSONDecodeError, KeyError):
                    continue
    new = 0
    upgraded = 0
    if dates:
        rows = fetch_espn_uefa(min(dates), max(dates))
        for r in rows:
            fid = r["fixture_id"]
            if fid not in index:
                index[fid] = len(lines)
                lines.append(json.dumps(r))
                new += 1
            else:
                old = json.loads(lines[index[fid]])
                if old.get("status") != "finished" and r["status"] == "finished":
                    lines[index[fid]] = json.dumps(r)
                    upgraded += 1
    if new or upgraded:
        with open(out, "w") as f:
            for line in lines:
                f.write(line + "\n")
    log.info("european_accumulated", new=new, upgraded=upgraded,
             total=len(lines), path=str(out))
    return out


def _reconstruct_missing_rounds(df: pd.DataFrame, league: str, season: str) -> pd.DataFrame:
    """Fill remaining unscheduled ordered pairings in the live double round-robin.

    Uses the circle method so no team plays more than once per reconstructed
    matchweek, anchored weekly after the latest known live fixture or today.
    """
    live = df[df["season"] == season]
    teams = sorted(set(live["home"]) | set(live["away"]))
    n = len(teams)
    if n < 2 or n % 2 != 0:
        return pd.DataFrame(columns=OUTPUT_COLS)
    existing = set(zip(live["home"], live["away"]))
    order = list(range(n))
    first_half: list[list[tuple[str, str]]] = []
    for _ in range(n - 1):
        first_half.append([(teams[order[i]], teams[order[n - 1 - i]]) for i in range(n // 2)])
        order = [order[0]] + [order[-1]] + order[1:-1]
    all_rounds = first_half + [[(b, a) for a, b in rd] for rd in first_half]
    missing_rounds = [
        [(h, a) for h, a in rd if (h, a) not in existing]
        for rd in all_rounds
    ]
    missing_rounds = [rd for rd in missing_rounds if rd]
    if not missing_rounds:
        return pd.DataFrame(columns=OUTPUT_COLS)
    last_dt = pd.to_datetime(live["date"]).max().date() if not live.empty else date.today()
    anchor = max(last_dt, date.today())
    days_ahead = (5 - anchor.weekday()) % 7 or 7
    start = anchor + timedelta(days=days_ahead)
    rows = []
    for wk, rd in enumerate(missing_rounds):
        dt = (start + timedelta(weeks=wk)).isoformat()
        for home, away in rd:
            fid = slugify(f"{league}-{season}-{dt}-{home}-v-{away}")
            rows.append({
                "fixture_id": fid, "date": dt, "season": season, "league": league,
                "home": home, "away": away, "home_goals": None, "away_goals": None,
                "status": "scheduled", "provenance": "schedule_reconstructed",
                "api_fixture_id": None, **{c: None for c in STAT_COLS},
            })
    log.info("schedule_reconstructed", league=league, remaining=len(rows),
             from_date=start.isoformat())
    return pd.DataFrame(rows, columns=OUTPUT_COLS)


def append_reconstructed_schedules(leagues: list[str]) -> None:
    """Refresh future ESPN fixtures through season end and fill missing pairings.

    For each non-PL league: drop old schedule_reconstructed and scheduled espn
    rows for the live season, pull published scheduled fixtures from ESPN through
    season end, then reconstruct any unscheduled round-robin pairings so full
    season simulations always play all 34/38 rounds.
    """
    from .uefa import fetch_espn_league
    season = str(settings.live_season)
    today = date.today().isoformat()
    end = f"{int(season) + 1}-06-30"
    for league in leagues:
        if league == "pl":
            continue  # PL has real scheduled fixtures from FPL
        path = settings.data_dir / f"fixtures_{league}.csv"
        df = pd.read_csv(path, dtype={"season": str})
        mask = ~((df["season"] == season) &
                 (df["provenance"].isin(["schedule_reconstructed", "espn"])) &
                 (df["status"] == "scheduled"))
        df = df[mask]
        rows = []
        try:
            espn_rows = fetch_espn_league(league, today, end)
        except Exception as exc:
            log.warning("espn_schedule_failed", league=league, error=str(exc)[:200])
            espn_rows = []
        for r in espn_rows:
            if r["status"] != "scheduled":
                continue
            fid = slugify(f"{league}-{season}-{r['date']}-{r['home']}-v-{r['away']}")
            rows.append({
                "fixture_id": fid, "date": r["date"], "season": season,
                "league": league, "home": r["home"], "away": r["away"],
                "home_goals": None, "away_goals": None,
                "status": "scheduled", "provenance": "espn",
                "api_fixture_id": None, **{c: None for c in STAT_COLS},
            })
        if rows:
            df = pd.concat([df, pd.DataFrame(rows, columns=OUTPUT_COLS)],
                           ignore_index=True)
        recon = _reconstruct_missing_rounds(df, league, season)
        if not recon.empty:
            df = pd.concat([df, recon], ignore_index=True)
        df = df.drop_duplicates(subset=["fixture_id"], keep="first")
        df = df.sort_values("date").reset_index(drop=True)
        df.to_csv(path, index=False)
        log.info("espn_fixtures_written", league=league, espn=len(rows),
                 reconstructed=len(recon))


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract fixtures per league/season.")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        choices=settings.league_order)
    parser.add_argument("--seasons", nargs="*",
                        default=settings.historical_seasons
                        + [settings.csv_only_season, settings.live_season])
    parser.add_argument("--prefer-csv", action="store_true",
                        help="Skip api-football/FPL and use CSVs everywhere.")
    parser.add_argument("--skip-europe", action="store_true",
                        help="Skip the European fixture accumulation.")
    args = parser.parse_args(argv)

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for league in args.leagues:
        df = extract_league(league, args.seasons, args.prefer_csv)
        out = settings.data_dir / f"fixtures_{league}.csv"
        df.to_csv(out, index=False)
        log.info("fixtures_written", league=league, rows=len(df),
                 finished=int((df["status"] == "finished").sum()), path=str(out))

    if not args.skip_europe and not args.prefer_csv:
        today = date.today()
        dates = [(today + timedelta(days=d)).isoformat() for d in (-1, 0, 1)]
        accumulate_european(dates)

    append_reconstructed_schedules(args.leagues)

    # Parquet lake mirror of the final fixtures CSVs (CSVs stay canonical).
    for league in args.leagues:
        src = settings.data_dir / f"fixtures_{league}.csv"
        write_parquet(pd.read_csv(src, dtype={"season": str}),
                      raw_lake_path(league))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
