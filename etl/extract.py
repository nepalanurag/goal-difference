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
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from datetime import date, datetime, timedelta
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
    """football-data.co.uk CSV for one league/season (download or local cache)."""
    csv_code = settings.leagues[league]["csv_code"]
    season_code = CSV_SEASON_CODE[season]
    url = f"{CSV_BASE}/{season_code}/{csv_code}.csv"
    cache_name = f"csv_{league}_{season}.csv"
    path = cached(cache_name)
    provenance = "csv_cached"
    if path is None:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
        except Exception as exc:
            raise RuntimeError(f"CSV download failed for {url}: {exc}") from exc
        # Strip UTF-8 BOM; the site redirects (handled by urlopen).
        text = raw.decode("utf-8-sig")
        cache_raw(cache_name, text)
        path = settings.raw_dir / cache_name
        provenance = "csv_download"
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
    for fx in fixtures:
        finished = bool(fx.get("finished"))
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


# ---------------------------------------------------------------- per-season
def extract_league_season(league: str, season: str, prefer_csv: bool) -> pd.DataFrame:
    if season in settings.historical_seasons and not prefer_csv:
        try:
            return fetch_api_fixtures(league, season)
        except Exception as exc:
            log.warning("api_failed_falling_back_to_csv", league=league,
                        season=season, error=str(exc)[:200])
    if season == settings.live_season and league == "pl" and not prefer_csv:
        try:
            return fetch_fpl()
        except Exception as exc:
            log.warning("fpl_failed_falling_back_to_csv", error=str(exc)[:200])
    # CSV path: only source for 2025/26, fallback everywhere else.
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


# ---------------------------------------------------------------- lineups
def fetch_bundesliga_lineups(n_matchdays: int = 5) -> Path:
    """Latest Bundesliga matchday lineups (for absence detection in team_news).

    Falls back gracefully: writes whatever the backend returns, never fails.
    """
    out = settings.data_dir / "lineups_bundesliga.json"
    base = ("https://bundesliga-web-prod.europe-west1.firebasedatabase.app"
            "/all/DFL-COM-000001/seasons/DFL-SEA-0001KA")
    result: dict = {"source": "bundesliga_official_firebase", "matchdays": []}
    try:
        req = urllib.request.Request(base + "/matchdays.json?shallow=true",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            md_ids = sorted(json.loads(resp.read()).keys())
        for md_id in md_ids[-n_matchdays:]:
            req = urllib.request.Request(f"{base}/matchdays/{md_id}.json",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                md = json.loads(resp.read())
            matches = md if isinstance(md, list) else list(md.values())
            day = {"matchday_id": md_id, "matches": []}
            for m in matches:
                try:
                    lineup = m.get("lineup", {}) or {}
                    day["matches"].append({
                        "date": m.get("matchDateTimeUTC", "")[:10],
                        "home": m.get("homeClubName") or m.get("homeTeamName"),
                        "away": m.get("awayClubName") or m.get("awayTeamName"),
                        "home_starters": [p.get("playerName") for p in
                                          (lineup.get("home") or {}).get("startXI", [])],
                        "away_starters": [p.get("playerName") for p in
                                          (lineup.get("away") or {}).get("startXI", [])],
                    })
                except Exception:
                    continue
            result["matchdays"].append(day)
        cache_raw("bundesliga_lineups.json", json.dumps(result))
    except Exception as exc:
        log.warning("bundesliga_lineups_failed", error=str(exc)[:200])
        result["note"] = f"fetch failed: {exc}"
    out.write_text(json.dumps(result, indent=1))
    log.info("bundesliga_lineups", matchdays=len(result["matchdays"]), path=str(out))
    return out


def append_reconstructed_schedules(leagues: list[str]) -> None:
    """Replace reconstructed/scheduled rows with real ESPN fixtures.

    The old round-robin reconstruction guessed matchups; ESPN publishes the
    real schedule. For each non-PL league: drop all schedule_reconstructed
    and espn rows for the live season, fetch the next 60 days from ESPN,
    and append with provenance="espn".
    """
    from .uefa import fetch_espn_league
    from .team_names import canonicalize_espn
    today = date.today().isoformat()
    end = (date.today() + timedelta(days=60)).isoformat()
    for league in leagues:
        if league == "pl":
            continue  # PL has real scheduled fixtures from FPL
        path = settings.data_dir / f"fixtures_{league}.csv"
        df = pd.read_csv(path, dtype={"season": str})
        season = str(settings.live_season)
        # Drop old guessed rows (and any previous ESPN pull) for live season.
        mask = ~((df["season"] == season) &
                 (df["provenance"].isin(["schedule_reconstructed", "espn"])))
        df = df[mask]
        rows = []
        for r in fetch_espn_league(league, today, end):
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
        df = df.drop_duplicates(subset=["fixture_id"], keep="first")
        df = df.sort_values("date").reset_index(drop=True)
        df.to_csv(path, index=False)
        log.info("espn_fixtures_written", league=league, n=len(rows))


def write_lineup_sources() -> Path:
    """Honest record of which leagues expose lineup data and which do not."""
    out = settings.data_dir / "lineup_sources.json"
    record = {
        "bundesliga": {
            "source": "bundesliga official Firebase (matchdays lineup nodes)",
            "lineups_available": True,
            "file": "lineups_bundesliga.json",
        },
        "pl": {
            "source": "FPL API (injuries, chance_of_playing, news)",
            "lineups_available": False,
            "note": "PL availability comes from FPL injury/news flags, not lineups.",
        },
        "laliga": {
            "source": "LaLiga apim public-service API",
            "lineups_available": False,
            "note": "No lineup endpoint found; player stats only.",
        },
        "seriea": {
            "source": "Serie A api-sdp (Deltatre)",
            "lineups_available": False,
            "note": "Match detail carries no lineups; no lineup sub-endpoint.",
        },
        "ligue1": {
            "source": "Ligue 1 ma-api",
            "lineups_available": False,
            "note": "No match/lineup endpoint found; statuses feed empty.",
        },
    }
    out.write_text(json.dumps(record, indent=1))
    return out


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

    fetch_bundesliga_lineups()
    write_lineup_sources()
    append_reconstructed_schedules(args.leagues)

    # Parquet lake mirror of the final fixtures CSVs (CSVs stay canonical).
    for league in args.leagues:
        src = settings.data_dir / f"fixtures_{league}.csv"
        write_parquet(pd.read_csv(src, dtype={"season": str}),
                      raw_lake_path(league))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
