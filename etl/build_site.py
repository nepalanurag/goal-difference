"""Build the static site into docs/ (GitHub Pages).

Pages: index, per-league hubs, fixture previews, team dashboards,
players, track record. All numbers come from the fitted models and the
feature tables; page copy is template-written from real values. No LLM
prose anywhere on the site.

Usage: python -m etl.build_site
"""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

import pandas as pd

from .config import settings
from .logging_setup import get_logger

log = get_logger(__name__)

LEAGUE_NAMES = {"pl": "Premier League", "laliga": "LaLiga",
                "bundesliga": "Bundesliga", "seriea": "Serie A",
                "ligue1": "Ligue 1"}
LEAGUE_ACCENT = {"pl": "#e90052", "laliga": "#ff4b44", "bundesliga": "#d20515",
                 "seriea": "#008fd7", "ligue1": "#00a651"}

# Base path the site is served from. GitHub Pages project sites live under
# /<repo>/, so every internal link and the stylesheet must carry this prefix.
# (Root-absolute "/" links 404 on project pages.)
SITE_BASE = "/goal-difference"


def slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def esc(text: object) -> str:
    return html.escape(str(text))


def pct(p: float) -> str:
    return f"{100 * p:.0f}%"


def dash(v: object) -> str:
    """Render a stat value, with a dash for missing data."""
    if v is None:
        return "-"
    try:
        if isinstance(v, float) and v != v:  # NaN
            return "-"
    except Exception:
        pass
    return esc(v)


def prob_bar(ph: float, pd_: float, pa: float, labels: bool = True) -> str:
    total = ph + pd_ + pa
    ph, pd_, pa = ph / total, pd_ / total, pa / total
    inner = ""
    if labels:
        inner = (f'<span class="seg home" style="width:{ph*100:.1f}%">{pct(ph)}</span>'
                 f'<span class="seg draw" style="width:{pd_*100:.1f}%">{pct(pd_)}</span>'
                 f'<span class="seg away" style="width:{pa*100:.1f}%">{pct(pa)}</span>')
    else:
        inner = (f'<span class="seg home" style="width:{ph*100:.1f}%"></span>'
                 f'<span class="seg draw" style="width:{pd_*100:.1f}%"></span>'
                 f'<span class="seg away" style="width:{pa*100:.1f}%"></span>')
    return f'<div class="probbar">{inner}</div>'


def prob_legend(home: str = "Home", away: str = "Away") -> str:
    return ('<div class="legend"><span class="sw home"></span>' + esc(home) +
            ' <span class="sw draw"></span>Draw <span class="sw away"></span>' +
            esc(away) + '</div>')


CSS = """
:root{
  --bg:#0a0d12; --panel:#11151d; --panel2:#161c26; --line:#232c3b;
  --text:#e9edf3; --muted:#8d97a8; --faint:#5b6474;
  --home:#4da3ff; --draw:#8d97a8; --away:#ff5d5d;
  --up:#3ddc84; --down:#ff5d5d;
  --mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);margin:0;
  font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  font-size:15px;line-height:1.5}
h1,h2,h3,.cond{font-family:'Barlow Condensed','Arial Narrow',sans-serif;
  text-transform:uppercase;letter-spacing:.04em;margin:0 0 .5em;font-weight:600}
h1{font-size:2.6em} h2{font-size:1.7em;border-bottom:1px solid var(--line);
  padding-bottom:.25em;margin-top:1.6em} h3{font-size:1.25em;color:var(--muted)}
a{color:var(--home);text-decoration:none} a:hover{text-decoration:underline}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px 60px}
.topbar{border-bottom:1px solid var(--line);background:#0d1117;
  position:sticky;top:0;z-index:10}
.topbar .wrap{display:flex;align-items:center;gap:22px;padding-top:14px;padding-bottom:14px}
.brand{font-family:'Barlow Condensed',sans-serif;font-size:1.5em;font-weight:700;
  text-transform:uppercase;letter-spacing:.06em;color:var(--text)}
.brand b{color:#ffd23f}
.nav{display:flex;gap:16px;flex-wrap:wrap;font-size:.92em}
.nav a{color:var(--muted)} .nav a:hover{color:var(--text)}
.hero{padding:44px 0 10px}
.hero p.lede{color:var(--muted);font-size:1.1em;max-width:640px}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:16px 18px}
.card h3{margin-top:0}
.kpi{font-family:var(--mono);font-size:1.9em;font-weight:700}
.kpi small{font-size:.45em;color:var(--muted);font-weight:400}
table{width:100%;border-collapse:collapse;font-size:.93em}
th{font-family:'Barlow Condensed',sans-serif;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted);font-weight:600;text-align:left;
  padding:8px 10px;border-bottom:1px solid var(--line);font-size:.95em}
td{padding:7px 10px;border-bottom:1px solid #1a212d}
tr:hover td{background:#141a24}
.num{font-family:var(--mono);text-align:right;white-space:nowrap}
.probbar{display:flex;height:26px;border-radius:4px;overflow:hidden;
  background:var(--panel2);border:1px solid var(--line);min-width:120px}
.seg{display:flex;align-items:center;justify-content:center;font-size:.75em;
  font-family:var(--mono);color:#0a0d12;font-weight:700;white-space:nowrap;
  overflow:hidden}
.seg.home{background:var(--home)} .seg.draw{background:var(--draw)}
.seg.away{background:var(--away)}
.legend{font-size:.8em;color:var(--muted);margin-top:4px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px}
.sw.home{background:var(--home)} .sw.draw{background:var(--draw)}
.sw.away{background:var(--away)}
.tag{display:inline-block;font-size:.72em;font-family:var(--mono);
  background:var(--panel2);border:1px solid var(--line);border-radius:4px;
  padding:2px 8px;color:var(--muted);margin:2px 4px 2px 0}
.formline{display:flex;gap:6px;margin:6px 0}
.badge{width:26px;height:26px;border-radius:4px;display:inline-flex;
  align-items:center;justify-content:center;font-weight:700;font-size:.8em;
  font-family:var(--mono);color:#0a0d12}
.badge.W{background:var(--up)} .badge.D{background:var(--draw)}
.badge.L{background:var(--down)}
.muted{color:var(--muted)} .faint{color:var(--faint)}
.small{font-size:.85em}
.mono{font-family:var(--mono)}
.positive{color:var(--up)} .negative{color:var(--down)}
.limit{border:1px dashed #3a4557;border-radius:8px;padding:14px 18px;
  color:var(--muted);font-size:.88em;margin-top:2.5em;background:#0d1117}
.limit b{color:var(--text)}
.footer{border-top:1px solid var(--line);margin-top:50px;padding:22px 0;
  color:var(--faint);font-size:.85em}
.fixlink{color:var(--text)} .fixlink:hover{color:var(--home)}
.scoreline{font-family:var(--mono);font-weight:700}
@media(max-width:640px){h1{font-size:1.9em}.wrap{padding:0 12px 40px}}
"""


def page_shell(title: str, body: str, league: str | None = None,
               updated: str = "") -> str:
    nav = ('<a href="{BASE}/">Home</a>' +
           "".join(f'<a href="{BASE}/leagues/{s}/">{LEAGUE_NAMES[s]}</a>'
                   for s in settings.league_order) +
           '<a href="{BASE}/players.html">Players</a>'
           '<a href="{BASE}/track-record.html">Track record</a>')
    accent = LEAGUE_ACCENT.get(league or "", "#ffd23f")
    nav = nav.replace("{BASE}", SITE_BASE)
    body = body.replace("{BASE}", SITE_BASE)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | Goal Difference</title>
<link rel="stylesheet" href="{SITE_BASE}/style.css">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>.brand b{{color:{accent}}} a{{color:{accent}}}</style>
</head><body>
<div class="topbar"><div class="wrap">
<div class="brand">Goal <b>Difference</b></div>
<nav class="nav">{nav}</nav></div></div>
<div class="wrap">{body}
<div class="limit"><b>Honest limits.</b> Probabilities are model outputs, not
betting advice. Live scores for non-PL leagues come from CSVs updated about a
day after matches. The FPL API and the official league JSON backends are
unofficial feeds with no SLA. Player coverage: Premier League from FPL;
other leagues from official league backends, with 2024/25 topscorers as the
labeled baseline. Team news: full injury data for the PL via FPL; other
leagues show absences detected from lineups, labeled "reason unconfirmed",
or state plainly when no data is published.</div>
<div class="footer">Goal Difference &middot; weekly model-driven matchday
analysis for Europe's top 5 leagues &middot; Poisson + gradient-boosted
models, refit weekly &middot; updated {esc(updated)}</div>
</div></body></html>"""


LIMITS_NOTE = ("Sources: api-football (2023/24-2024/25), football-data.co.uk "
               "CSVs, FPL API (PL live, unofficial), official league JSON "
               "backends (player stats). See the honest-limits box below.")


# ---------------------------------------------------------------- data access
class LeagueData:
    """All loaded artifacts for one league."""

    def __init__(self, league: str):
        self.league = league
        d = settings.data_dir
        self.fixtures = pd.read_csv(d / f"fixtures_{league}.csv",
                                    dtype={"season": str})
        self.features = pd.read_csv(d / f"features_{league}.csv")
        self.h2h = json.loads((d / f"h2h_{league}.json").read_text())
        self.odds = pd.read_csv(d / f"odds_{league}.csv") \
            if (d / f"odds_{league}.csv").exists() else pd.DataFrame()
        self.params = json.loads((d / f"params_{league}.json").read_text()) \
            if (d / f"params_{league}.json").exists() else {}
        self.team_news = json.loads((d / f"team_news_{league}.json").read_text()) \
            if (d / f"team_news_{league}.json").exists() else {}
        self.finished = self.fixtures[self.fixtures.status == "finished"].copy()
        self.upcoming = self.fixtures[self.fixtures.status == "scheduled"].copy()
        self.upcoming = self.upcoming.sort_values("date").reset_index(drop=True)

    def table(self) -> pd.DataFrame:
        """Live-season league table."""
        fin = self.finished[self.finished.season == settings.live_season]
        rows = []
        for team in sorted(set(fin.home) | set(fin.away)):
            h = fin[fin.home == team]
            a = fin[fin.away == team]
            w = int((h.home_goals > h.away_goals).sum()
                    + (a.away_goals > a.home_goals).sum())
            dr = int((h.home_goals == h.away_goals).sum()
                     + (a.away_goals == a.home_goals).sum())
            l = len(h) + len(a) - w - dr
            gf = int(h.home_goals.sum() + a.away_goals.sum())
            ga = int(h.away_goals.sum() + a.home_goals.sum())
            rows.append({"team": team, "p": len(h) + len(a), "w": w, "d": dr,
                         "l": l, "gf": gf, "ga": ga, "gd": gf - ga,
                         "pts": 3 * w + dr})
        t = pd.DataFrame(rows).sort_values(["pts", "gd", "gf"],
                                           ascending=False).reset_index(drop=True)
        t.index = t.index + 1
        return t

    def last5(self, team: str) -> pd.DataFrame:
        m = self.finished[(self.finished.home == team) |
                          (self.finished.away == team)]
        return m.sort_values("date", ascending=False).head(5)

    def latest_team_features(self, team: str) -> dict:
        """Most recent feature row for a team (h_ or a_ side as appropriate)."""
        f = self.features
        rows = f[((f.home == team) | (f.away == team))]
        if rows.empty:
            return {}
        r = rows.sort_values("date").iloc[-1]
        side = "h_" if r["home"] == team else "a_"
        opp_side = "a_" if side == "h_" else "h_"
        out = {"_side": side}
        for c in f.columns:
            if c.startswith(side):
                out[c[len(side):]] = r[c]
            elif c.startswith(opp_side):
                out["opp_" + c[len(opp_side):]] = r[c]
        out["h2h_edge"] = r["h2h_edge"] if side == "h_" else 1 - r["h2h_edge"]
        return out


def load_predictions(league: str) -> pd.DataFrame:
    from .fit import predict_upcoming
    try:
        return predict_upcoming(league)
    except Exception as exc:
        log.warning("predictions_failed", league=league, error=str(exc)[:160])
        return pd.DataFrame()


def form_badges(last5: pd.DataFrame, team: str) -> str:
    out = []
    for _, r in last5.sort_values("date").iterrows():
        if r.home_goals == r.away_goals:
            out.append('<span class="badge D">D</span>')
        elif (r.home == team and r.home_goals > r.away_goals) or \
             (r.away == team and r.away_goals > r.home_goals):
            out.append('<span class="badge W">W</span>')
        else:
            out.append('<span class="badge L">L</span>')
    return '<div class="formline">' + "".join(out) + "</div>"


def last5_scores(last5: pd.DataFrame, team: str) -> str:
    rows = []
    for _, r in last5.sort_values("date", ascending=False).iterrows():
        if r.home == team:
            txt = f"{r.away} (H) {int(r.home_goals)}-{int(r.away_goals)}"
        else:
            txt = f"{r.home} (A) {int(r.away_goals)}-{int(r.home_goals)}"
        rows.append(f'<div class="small muted"><span class="mono faint">{r.date}</span> '
                    f'{esc(txt)}</div>')
    return "".join(rows) or '<div class="muted small">No games yet.</div>'


def momentum_word(m: float) -> tuple[str, str]:
    if m > 0.3:
        return "improving", "positive"
    if m < -0.3:
        return "fading", "negative"
    return "steady", "muted"


# ---------------------------------------------------------------- index page
def build_index(datas: dict[str, LeagueData],
                preds: dict[str, pd.DataFrame], updated: str) -> str:
    cards = []
    for league in settings.league_order:
        ld = datas[league]
        t = ld.table()
        leader = t.iloc[0]
        p_title = ""
        if not ld.odds.empty:
            row = ld.odds[ld.odds.team == leader.team]
            if not row.empty:
                p_title = f" &middot; title {pct(row.iloc[0].p_title)}"
        n_up = len(ld.upcoming)
        cards.append(f"""<div class="card">
<h3 style="color:{LEAGUE_ACCENT[league]}">{LEAGUE_NAMES[league]}</h3>
<div class="kpi">{esc(leader.team)}<br><small>{leader.pts} pts after {leader.p}</small></div>
<div class="small muted">Next: {n_up} fixtures to play{p_title}</div>
<div style="margin-top:10px"><a href="{BASE}/leagues/{league}/">League hub &rarr;</a></div>
</div>""")
    league_cards = '<div class="grid g3">' + "".join(cards) + "</div>"

    # In-form teams: top ppg_l5 per league.
    form_rows = []
    for league in settings.league_order:
        ld = datas[league]
        seen = []
        for team in sorted(set(ld.finished.home) | set(ld.finished.away)):
            f = ld.latest_team_features(team)
            if f:
                seen.append((team, f.get("ppg_l5", 0), f.get("ppg", 0)))
        seen.sort(key=lambda x: -x[1])
        for team, l5, season in seen[:2]:
            trend = "up" if l5 > season else ("down" if l5 < season else "flat")
            form_rows.append(
                f"<tr><td>{esc(team)}</td><td class='muted'>{LEAGUE_NAMES[league]}</td>"
                f"<td class='num'>{l5:.2f}</td><td class='num muted'>{season:.2f}</td>"
                f"<td>{trend}</td></tr>")
    form_table = ("""<table><tr><th>Team</th><th>League</th><th class="num">Last-5 PPG</th>
<th class="num">Season PPG</th><th>Trend</th></tr>""" + "".join(form_rows) + "</table>")

    # Key matchups: upcoming fixtures where both sides are top 6.
    matchups = []
    for league in settings.league_order:
        ld = datas[league]
        t = ld.table()
        top6 = set(t.head(6).team)
        pr = preds.get(league, pd.DataFrame())
        if pr.empty:
            continue
        for _, r in pr.head(12).iterrows():
            if r.home in top6 and r.away in top6:
                matchups.append(
                    f"""<div class="card"><div class="cond">{LEAGUE_NAMES[league]}
<span class="faint mono small">{r.date}</span></div>
<div style="font-size:1.2em"><a class="fixlink" href="{BASE}/leagues/{league}/fixtures/{r.fixture_id}.html">
{esc(r.home)} v {esc(r.away)}</a></div>
{prob_bar(r.p_home_ens, r.p_draw_ens, r.p_away_ens)}
{prob_legend(r.home, r.away)}</div>""")
                if len(matchups) >= 6:
                    break
        if len(matchups) >= 6:
            break
    matchup_html = ('<div class="grid g2">' + "".join(matchups) + "</div>"
                    if matchups else '<p class="muted">No top-six clashes this week.</p>')

    body = f"""<div class="hero">
<h1>What the models see this week</h1>
<p class="lede">Weekly model-driven matchday analysis for Europe's top 5
leagues. Poisson and gradient-boosted models on four seasons of results,
refit every matchday. Numbers first.</p>
<p class="small muted">{esc(LIMITS_NOTE)}</p></div>
<h2>Leagues</h2>{league_cards}
<h2>In-form teams</h2>
<p class="muted small">Last-5 points per game against the season average.</p>
{form_table}
<h2>Key matchups</h2>{matchup_html}"""
    return page_shell("This week's model view", body, updated=updated)


# ---------------------------------------------------------------- league page
def build_league(league: str, ld: LeagueData, pred: pd.DataFrame,
                 updated: str) -> str:
    t = ld.table()
    rows = []
    for pos, r in t.iterrows():
        odds = ""
        if not ld.odds.empty:
            o = ld.odds[ld.odds.team == r.team]
            if not o.empty:
                o = o.iloc[0]
                odds = (f"<td class='num'>{pct(o.p_title)}</td>"
                        f"<td class='num'>{pct(o.p_top4)}</td>"
                        f"<td class='num'>{pct(o.p_relegation)}</td>")
        rows.append(
            f"<tr><td class='num'>{pos}</td>"
            f"<td><a href=\"{BASE}/leagues/{league}/teams/{slug(r.team)}.html\">"
            f"{esc(r.team)}</a></td><td class='num'>{r.p}</td>"
            f"<td class='num'>{r.w}</td><td class='num'>{r.d}</td>"
            f"<td class='num'>{r.l}</td><td class='num'>{r.gd:+d}</td>"
            f"<td class='num'><b>{r.pts}</b></td>{odds}</tr>")
    odds_head = ("<th class='num'>Title</th><th class='num'>Top 4</th>"
                 "<th class='num'>Releg.</th>") if not ld.odds.empty else ""
    table = (f"""<table><tr><th class="num">#</th><th>Team</th><th class="num">P</th>
<th class="num">W</th><th class="num">D</th><th class="num">L</th>
<th class="num">GD</th><th class="num">Pts</th>{odds_head}</tr>""" +
             "".join(rows) + "</table>")

    # This matchday: first cluster of upcoming fixtures.
    fix_html = ""
    if not pred.empty:
        first = pred.iloc[0].date
        week = pred[pd.to_datetime(pred.date) <=
                    pd.to_datetime(first) + pd.Timedelta(days=4)]
        cards = []
        for _, r in week.iterrows():
            cards.append(f"""<div class="card">
<div class="cond"><span class="faint mono small">{r.date}</span></div>
<div style="font-size:1.15em;margin-bottom:8px"><a class="fixlink"
href="{BASE}/leagues/{league}/fixtures/{r.fixture_id}.html">{esc(r.home)} v {esc(r.away)}</a></div>
{prob_bar(r.p_home_ens, r.p_draw_ens, r.p_away_ens)}
{prob_legend(r.home, r.away)}
<div class="small muted" style="margin-top:6px">xG {r.xg_home:.2f} - {r.xg_away:.2f}</div>
</div>""")
        fix_html = f"<h2>This matchday</h2><div class='grid g2'>{''.join(cards)}</div>"
    else:
        fix_html = "<h2>This matchday</h2><p class='muted'>No fixtures scheduled.</p>"

    # Recent results.
    recent = ld.finished.sort_values("date", ascending=False).head(8)
    res_rows = "".join(
        f"<tr><td class='muted mono small'>{r.date}</td><td>{esc(r.home)}</td>"
        f"<td class='scoreline'>{int(r.home_goals)} - {int(r.away_goals)}</td>"
        f"<td>{esc(r.away)}</td></tr>" for _, r in recent.iterrows())
    results = f"<h2>Recent results</h2><table>{res_rows}</table>"

    body = f"""<div class="hero"><h1 style="color:{LEAGUE_ACCENT[league]}">
{LEAGUE_NAMES[league]}</h1>
<p class="lede">Live table, title odds from 10,000 Monte Carlo simulations,
and this matchday's fixtures with ensemble probabilities.</p></div>
<h2>Table and odds</h2>{table}
<p class="small faint">Odds: share of 10,000 season simulations (seed 42).</p>
{fix_html}{results}"""
    return page_shell(LEAGUE_NAMES[league], body, league=league, updated=updated)


# ---------------------------------------------------------------- fixture page
def team_news_box(league: str, ld: LeagueData, home: str, away: str) -> str:
    tn = ld.team_news
    if not tn:
        return ""
    source = esc(tn.get("source", ""))
    teams = tn.get("teams", {})
    parts = []
    for team in (home, away):
        info = teams.get(team, {})
        if not info:
            continue
        out = info.get("out", [])
        doubtful = info.get("doubtful", [])
        absent = info.get("absent", [])
        lines = []
        def _nm(p):
            return p.get("name", p.get("player", "?")) if isinstance(p, dict) else p
        for p in out:
            reason = (p.get("news") or p.get("reason") or "") if isinstance(p, dict) else ""
            lines.append(f"<div class='small'><b>{esc(_nm(p))}</b> out"
                         + (f" <span class='muted'>&mdash; {esc(reason[:120])}</span>" if reason else "") + "</div>")
        for p in doubtful:
            lines.append(f"<div class='small'><b>{esc(_nm(p))}</b> doubtful</div>")
        for p in absent:
            lines.append(f"<div class='small'><b>{esc(_nm(p))}</b> "
                         f"<span class='muted'>absent &mdash; reason unconfirmed</span></div>")
        if lines:
            parts.append(f"<div><h3>{esc(team)}</h3>{''.join(lines)}</div>")
    availability = tn.get("availability")
    inner = "".join(parts)
    if not inner and availability:
        inner = f"<p class='muted small'>{esc(availability)}</p>"
    if not inner:
        return ""
    return (f"<h2>Team news</h2><div class='card'>{inner}"
            f"<p class='small faint' style='margin-bottom:0'>Source: {source}</p></div>")


def euro_note(league: str, ld: LeagueData, home: str, away: str,
              feats: dict) -> str:
    notes = []
    for team, prefix in ((home, "h_"), (away, "a_")):
        gap = feats.get(prefix + "euro_days_since", 999)
        if gap != 999 and gap <= 4:
            notes.append(f"{team} played in Europe {int(gap)} days ago &mdash; rotation risk.")
        elif gap != 999 and gap <= 7:
            notes.append(f"{team} played in Europe {int(gap)} days ago.")
    if not notes:
        return ""
    return ("<div class='card'><h3>European congestion</h3><p class='small'>"
            + "<br>".join(esc(n) for n in notes) + "</p></div>")


def build_fixture(league: str, ld: LeagueData, row: pd.Series,
                  feats: dict, updated: str) -> str:
    home, away = row.home, row.away
    hf = ld.latest_team_features(home)
    af = ld.latest_team_features(away)

    def form_section(team: str, f: dict) -> str:
        l5 = ld.last5(team)
        mw, cls = momentum_word(f.get("momentum", 0))
        return f"""<div class="card"><h3>{esc(team)}</h3>
{form_badges(l5, team)}{last5_scores(l5, team)}
<table class="small">
<tr><td class="muted">Attack (goals/game)</td><td class="num">{f.get('gf_pg', 0):.2f}</td>
<td class="muted">last-5</td><td class="num">{f.get('gf_pg_l5', 0):.2f}</td></tr>
<tr><td class="muted">Defense (conceded/game)</td><td class="num">{f.get('ga_pg', 0):.2f}</td>
<td class="muted">last-5</td><td class="num">{f.get('ga_pg_l5', 0):.2f}</td></tr>
<tr><td class="muted">Shot dominance / game</td><td class="num">{f.get('shot_diff_pg', 0):+.1f}</td>
<td class="muted">on target / game</td><td class="num">{f.get('sot_pg', 0):.1f}</td></tr>
<tr><td class="muted">Clean sheets</td><td class="num">{pct(f.get('cs_rate', 0))}</td>
<td class="muted">Failed to score</td><td class="num">{pct(f.get('fts_rate', 0))}</td></tr>
<tr><td class="muted">Momentum</td><td colspan="3" class="num"><span class="{cls}">{mw}</span>
<span class="faint">({f.get('momentum', 0):+.2f} PPG vs season)</span></td></tr>
<tr><td class="muted">Discipline</td><td class="num">{f.get('fouls_pg', 0):.1f} fouls</td>
<td class="muted">cards / game</td><td class="num">{f.get('cards_pg', 0):.1f}</td></tr>
</table></div>"""

    # H2H.
    key = f"{home} vs {away}"
    h2h_html = "<p class='muted'>No previous meetings in the data.</p>"
    if key in ld.h2h:
        rec = ld.h2h[key]
        at = rec["alltime"]
        last5 = "".join(
            f"<div class='small'><span class='mono faint'>{m['date']}</span> "
            f"{esc(m['home'])} {int(m['home_goals'])}-{int(m['away_goals'])} "
            f"{esc(m['away'])}</div>" for m in rec["last5"])
        h2h_html = (f"<div class='kpi'>{at['w']}<small>W</small> {at['d']}<small>D</small> "
                    f"{at['l']}<small>L</small></div>"
                    f"<p class='small muted'>All-time, {esc(home)} perspective. Last 5:</p>{last5}")

    probs = f"""<div class="card"><h3>Model probabilities</h3>
<table><tr><th></th><th class="num">Home</th><th class="num">Draw</th><th class="num">Away</th></tr>
<tr><td>Poisson</td><td class="num">{pct(row.p_home_poisson)}</td>
<td class="num">{pct(row.p_draw_poisson)}</td><td class="num">{pct(row.p_away_poisson)}</td></tr>
<tr><td>Gradient boosting</td><td class="num">{pct(row.p_home_ml)}</td>
<td class="num">{pct(row.p_draw_ml)}</td><td class="num">{pct(row.p_away_ml)}</td></tr>
<tr><td><b>Ensemble</b></td><td class="num"><b>{pct(row.p_home_ens)}</b></td>
<td class="num"><b>{pct(row.p_draw_ens)}</b></td><td class="num"><b>{pct(row.p_away_ens)}</b></td></tr>
</table>{prob_bar(row.p_home_ens, row.p_draw_ens, row.p_away_ens)}
{prob_legend(home, away)}
<p class="small muted">Expected goals: <span class="mono">{row.xg_home:.2f} - {row.xg_away:.2f}</span>.
Each row sums to 100%.</p></div>"""

    # What to expect: key numbers card.
    edge = feats.get("h2h_edge", 0.5)
    expect = f"""<div class="card"><h3>What to expect</h3><table class="small">
<tr><td class="muted">Headline</td><td><b>{esc(home if row.p_home_ens >= row.p_away_ens else away)}</b>
<span class="muted">favored at</span> <b>{pct(max(row.p_home_ens, row.p_away_ens))}</b>
<span class="muted">(ensemble)</span></td></tr>
<tr><td class="muted">Attack vs defense</td><td>{esc(home)} score
<span class="mono">{hf.get('gf_pg_l5', 0):.2f}</span>/game lately; {esc(away)} concede
<span class="mono">{af.get('ga_pg_l5', 0):.2f}</span>/game lately</td></tr>
<tr><td class="muted">Shot dominance</td><td>{esc(home)} <span class="mono">{hf.get('shot_diff_pg', 0):+.1f}</span>
vs {esc(away)} <span class="mono">{af.get('shot_diff_pg', 0):+.1f}</span> per game
<span class="faint">(shot-based)</span></td></tr>
<tr><td class="muted">Head-to-head edge</td><td>{esc(home)} win
<span class="mono">{pct(edge)}</span> of past meetings</td></tr>
<tr><td class="muted">Rest</td><td>{esc(home)} {int(feats.get('h_rest_days', 7))} days,
{esc(away)} {int(feats.get('a_rest_days', 7))} days since last match</td></tr>
</table></div>"""

    body = f"""<div class="hero"><p class="cond muted">{LEAGUE_NAMES[league]}
&middot; <span class="mono">{esc(row.date)}</span></p>
<h1>{esc(home)} <span class="faint">v</span> {esc(away)}</h1></div>
<h2>How they're playing</h2>
<div class="grid g2">{form_section(home, hf)}{form_section(away, af)}</div>
{euro_note(league, ld, home, away, feats)}
<h2>Head to head</h2><div class="card">{h2h_html}</div>
{team_news_box(league, ld, home, away)}
<h2>Prediction</h2><div class="grid g2">{probs}{expect}</div>"""
    return page_shell(f"{home} v {away}", body, league=league, updated=updated)


# ---------------------------------------------------------------- team page
def build_team(league: str, ld: LeagueData, team: str,
               players_pl: dict, updated: str) -> str:
    f = ld.latest_team_features(team)
    t = ld.table()
    pos = int(t[t.team == team].index[0]) if team in t.team.values else 0
    l5 = ld.last5(team)
    mw, cls = momentum_word(f.get("momentum", 0))

    # Next opponent + next-5 difficulty.
    up = ld.upcoming[(ld.upcoming.home == team) | (ld.upcoming.away == team)]
    next_opp = ""
    difficulty = ""
    if not up.empty:
        r0 = up.iloc[0]
        opp = r0.away if r0.home == team else r0.home
        venue = "home" if r0.home == team else "away"
        key = f"{team} vs {opp}"
        h2h_txt = ""
        if key in ld.h2h:
            at = ld.h2h[key]["alltime"]
            h2h_txt = f" (all-time {at['w']}W {at['d']}D {at['l']}L)"
        next_opp = (f"<div class='card'><h3>Next: {esc(opp)} ({venue})</h3>"
                    f"<p class='small'>{esc(r0.date)}{h2h_txt} &mdash; "
                    f"<a href='/leagues/{league}/fixtures/{r0.fixture_id}.html'>preview &rarr;</a></p></div>")
        opps = [(r.away if r.home == team else r.home) for _, r in up.head(5).iterrows()]
        avg_pts = sum(float(t[t.team == o].pts.iloc[0]) if o in t.team.values else 0
                      for o in opps) / max(len(opps), 1)
        difficulty = (f"<div class='card'><h3>Next 5: {', '.join(esc(o) for o in opps)}</h3>"
                      f"<p class='small muted'>Opponents average "
                      f"<span class='mono'>{avg_pts:.1f}</span> points.</p></div>")

    # European record this season.
    euro_html = ""
    try:
        import json as _json
        ej = settings.data_dir / "european_fixtures.jsonl"
        rec = [ _json.loads(l) for l in ej.read_text().splitlines() if l.strip()] \
            if ej.exists() else []
        mine = [m for m in rec if m["home"] == team or m["away"] == team]
        if mine:
            w = sum(1 for m in mine if (m["home"] == team and (m["home_goals"] or 0) > (m["away_goals"] or 0)) or
                     (m["away"] == team and (m["away_goals"] or 0) > (m["home_goals"] or 0)))
            euro_html = (f"<div class='card'><h3>Europe this season</h3>"
                         f"<p>{w}W in {len(mine)} European fixtures tracked.</p></div>")
    except Exception:
        pass

    # Squad panel (PL only, from FPL).
    squad = ""
    if league == "pl" and players_pl:
        xi = players_pl.get("in_form_xi", {})
        xi_html = "".join(
            f"<div class='small'><span class='muted'>{pos_}:</span> "
            + ", ".join(esc(p) for p in picks[:4]) + "</div>"
            for pos_, picks in xi.items() if picks)
        squad = (f"<h2>Squad watch</h2><div class='card'><h3>In-form XI</h3>{xi_html}"
                 f"<p class='small faint'>From FPL form (unofficial).</p></div>")

    tn = ld.team_news.get("teams", {}).get(team, {}) if ld.team_news else {}
    avail = ""
    if tn:
        items = []
        def _nm2(p):
            return p.get("name", p.get("player", "?")) if isinstance(p, dict) else p
        for p in tn.get("out", []):
            items.append(f"<div class='small'><b>{esc(_nm2(p))}</b> out</div>")
        for p in tn.get("doubtful", []):
            items.append(f"<div class='small'><b>{esc(_nm2(p))}</b> doubtful</div>")
        if items:
            avail = f"<div class='card'><h3>Availability</h3>{''.join(items)}</div>"

    body = f"""<div class="hero"><p class="cond muted">{LEAGUE_NAMES[league]}</p>
<h1>{esc(team)}</h1>
<p class="lede">{pos}{ordinal(pos)} &middot; {t[t.team == team].pts.iloc[0] if team in t.team.values else 0} points
&middot; momentum: <span class="{cls}">{mw}</span></p></div>
<h2>Rolling form</h2><div class="card">{form_badges(l5, team)}{last5_scores(l5, team)}</div>
<h2>Season dashboard</h2><div class="grid g2">
<div class="card"><h3>Home / away splits</h3><table class="small">
<tr><td class="muted">Home PPG</td><td class="num">{f.get('home_ppg', 0):.2f}</td>
<td class="muted">Away PPG</td><td class="num">{f.get('away_ppg', 0):.2f}</td></tr>
<tr><td class="muted">Home goals for/against</td><td class="num">{f.get('home_gf_pg', 0):.2f} / {f.get('home_ga_pg', 0):.2f}</td>
<td class="muted">Away</td><td class="num">{f.get('away_gf_pg', 0):.2f} / {f.get('away_ga_pg', 0):.2f}</td></tr>
</table></div>
<div class="card"><h3>Attack / defense</h3><table class="small">
<tr><td class="muted">Scored / game</td><td class="num">{f.get('gf_pg', 0):.2f}</td>
<td class="muted">last-5</td><td class="num">{f.get('gf_pg_l5', 0):.2f}</td></tr>
<tr><td class="muted">Conceded / game</td><td class="num">{f.get('ga_pg', 0):.2f}</td>
<td class="muted">last-5</td><td class="num">{f.get('ga_pg_l5', 0):.2f}</td></tr>
<tr><td class="muted">Shot dominance</td><td class="num">{f.get('shot_diff_pg', 0):+.1f}</td>
<td class="muted">shots on target</td><td class="num">{f.get('sot_pg', 0):.1f}</td></tr>
<tr><td class="muted">Clean sheets</td><td class="num">{pct(f.get('cs_rate', 0))}</td>
<td class="muted">Failed to score</td><td class="num">{pct(f.get('fts_rate', 0))}</td></tr>
<tr><td class="muted">Discipline</td><td class="num">{f.get('fouls_pg', 0):.1f} fouls/g</td>
<td class="muted">cards</td><td class="num">{f.get('cards_pg', 0):.1f}/g</td></tr>
</table></div></div>
<div class="grid g2">{next_opp}{difficulty}</div>
<div class="grid g2">{euro_html}{avail}</div>
{squad}"""
    return page_shell(team, body, league=league, updated=updated)


def ordinal(n: int) -> str:
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# ---------------------------------------------------------------- players
def build_players(datas: dict[str, LeagueData], updated: str) -> str:
    d = settings.data_dir
    sections = []

    # Premier League: FPL form watch.
    pl_path = d / "players_pl.json"
    if pl_path.exists():
        pl = json.loads(pl_path.read_text())
        players = sorted(pl.get("players", []),
                         key=lambda p: float(p.get("form") or 0), reverse=True)[:30]
        rows = "".join(
            f"<tr><td>{esc(p.get('name', ''))}</td>"
            f"<td class='muted'>{esc(p.get('team', ''))}</td>"
            f"<td class='muted'>{esc(p.get('position', ''))}</td>"
            f"<td class='num'><b>{p.get('form', '')}</b></td>"
            f"<td class='num'>{p.get('total_points', '')}</td>"
            f"<td class='num'>{p.get('goals', '')}</td>"
            f"<td class='num'>{p.get('assists', '')}</td>"
            f"<td class='num'>{p.get('minutes', '')}</td>"
            f"<td class='num'>{p.get('ict_index', '')}</td>"
            f"<td class='num'>{p.get('now_cost', '')}</td>"
            f"<td class='num'>{p.get('points_per_million', '')}</td></tr>"
            for p in players)
        xi = pl.get("in_form_xi", {})
        xi_html = "".join(
            f"<div class='small'><span class='muted'>{esc(k)}:</span> "
            + ", ".join(esc(x.get("name", x) if isinstance(x, dict) else x)
                         for x in v[:4]) + "</div>"
            for k, v in xi.items() if v)
        risers = "".join(
            f"<div class='small'>{esc(r.get('name', ''))} "
            f"<span class='positive'>+{r.get('form_change', '')}</span></div>"
            for r in pl.get("risers", [])[:8])
        sections.append(f"""<h2>Premier League &mdash; form watch</h2>
<p class="small muted">Source: FPL API (unofficial). Form = average points over the last 30 days.</p>
<div class="grid g2"><div class="card"><h3>In-form XI</h3>{xi_html or '<p class="muted">-</p>'}</div>
<div class="card"><h3>Risers this week</h3>{risers or '<p class="muted">-</p>'}</div></div>
<table><tr><th>Player</th><th>Team</th><th>Pos</th><th class="num">Form</th>
<th class="num">Pts</th><th class="num">G</th><th class="num">A</th>
<th class="num">Min</th><th class="num">ICT</th><th class="num">Cost</th>
<th class="num">Pts/m</th></tr>{rows}</table>""")

    # Other leagues: official backend rankings.
    backend_labels = {
        "laliga": ("LaLiga", "LaLiga official data backend (apim.laliga.com)"),
        "bundesliga": ("Bundesliga", "Bundesliga official Firebase backend"),
        "seriea": ("Serie A", "Serie A official data backend (api-sdp.legaseriea.it)"),
        "ligue1": ("Ligue 1", "Ligue 1 official backend (ma-api.ligue1.fr)"),
    }
    for league, (name, source) in backend_labels.items():
        p = d / f"player_rankings_official_{league}.json"
        if not p.exists():
            sections.append(f"<h2>{name}</h2><p class='muted small'>"
                            f"Official backend unreachable this week; "
                            f"2024/25 topscorers below are the fallback.</p>")
            continue
        data = json.loads(p.read_text())
        players = data.get("players") or data.get("rankings") or []
        rows = "".join(
            f"<tr><td>{esc(x.get('name', ''))}</td>"
            f"<td class='muted'>{dash(x.get('team'))}</td>"
            f"<td class='num'>{dash(x.get('goals'))}</td>"
            f"<td class='num'>{dash(x.get('assists'))}</td>"
            f"<td class='num'>{dash(x.get('appearances', x.get('minutes')))}</td></tr>"
            for x in players[:25])
        sections.append(f"""<h2>{name} &mdash; current season</h2>
<p class="small muted">Source: {esc(source)} (unofficial feed, no SLA).</p>
<table><tr><th>Player</th><th>Team</th><th class="num">Goals</th>
<th class="num">Assists</th><th class="num">Apps/Min</th></tr>{rows}</table>""")

    # 2024/25 topscorers baseline for all leagues.
    ts_path = d / "topscorers_2425.json"
    if ts_path.exists():
        ts = json.loads(ts_path.read_text())
        leagues_ts = ts.get("leagues", ts)
        for league in settings.league_order:
            entries = (leagues_ts.get(league) or [])[:20]
            if not entries:
                continue
            rows = "".join(
                f"<tr><td>{esc(e.get('player', ''))}</td>"
                f"<td class='muted'>{esc(e.get('team', ''))}</td>"
                f"<td class='num'>{dash(e.get('goals'))}</td>"
                f"<td class='num'>{dash(e.get('assists'))}</td>"
                f"<td class='num'>{dash(e.get('appearances'))}</td>"
                f"<td class='num'>{dash(e.get('rating'))}</td></tr>"
                for e in entries)
            sections.append(f"""<h2>{LEAGUE_NAMES[league]} &mdash; 2024/25 top scorers</h2>
<p class="small muted">Source: api-football topscorers, season 2024/25 (labeled baseline).</p>
<table><tr><th>Player</th><th>Team</th><th class="num">Goals</th>
<th class="num">Assists</th><th class="num">Apps</th><th class="num">Rating</th></tr>
{rows}</table>""")

    body = ('<div class="hero"><h1>Players</h1><p class="lede">Who is in form, '
            'per league, each source labeled.</p></div>' + "".join(sections))
    return page_shell("Players", body, updated=updated)


# ---------------------------------------------------------------- track record
def build_track_record(datas: dict[str, LeagueData], updated: str) -> str:
    sections = []
    for league in settings.league_order:
        ld = datas[league]
        wf = (ld.params or {}).get("walkforward", {})
        if not wf:
            sections.append(f"<h2>{LEAGUE_NAMES[league]}</h2>"
                            "<p class='muted'>Models not fitted yet.</p>")
            continue
        rows = ""
        for model in ("poisson", "xgb_tiny", "xgb_reg", "xgb_base", "lgbm_a",
                      "lgbm_b", "ensemble", "baseline"):
            m = wf.get(model, {})
            if not m:
                continue
            star = " *" if wf.get("chosen_ml") == model else ""
            rows += (f"<tr><td>{esc(model)}{star}</td>"
                     f"<td class='num'>{m.get('logloss', 0):.4f}</td>"
                     f"<td class='num'>{pct(m.get('accuracy', 0))}</td></tr>")
        ah = wf.get("always_home_accuracy")
        note = (f"<p class='small faint'>Always-pick-home accuracy: {pct(ah)}. "
                f"Baseline log-loss uses each league's historical outcome rates. "
                f"* = the ML config used for this league's headline probabilities.</p>"
                if ah else "")
        contenders = [m for m in ("poisson", "ensemble") if wf.get(m)]
        best = min(contenders, key=lambda m: wf[m]["logloss"])
        verdict = ("The ensemble beats the naive baseline here." if
                   wf[best]["logloss"] < wf["baseline"]["logloss"]
                   else "No model beats the naive baseline in this league yet. "
                        "The numbers stay up regardless.")
        sections.append(f"""<h2>{LEAGUE_NAMES[league]}</h2>
<p class="small muted">Walk-forward (time-series split) on all finished fixtures.
Lower log-loss is better. {esc(verdict)}</p>
<table><tr><th>Model</th><th class="num">Log-loss</th><th class="num">Accuracy</th></tr>
{rows}</table>{note}""")

    # Ledger status.
    ledgers = []
    for league in settings.league_order:
        p = settings.data_dir / f"predictions_ledger_{league}.csv"
        if p.exists():
            df = pd.read_csv(p)
            scored = int(df["result"].notna().sum()) if "result" in df else 0
            ledgers.append(f"<tr><td>{LEAGUE_NAMES[league]}</td>"
                           f"<td class='num'>{len(df)}</td>"
                           f"<td class='num'>{scored}</td></tr>")
    ledger_html = ("<h2>Prediction ledgers</h2><table><tr><th>League</th>"
                   "<th class='num'>Predicted</th><th class='num'>Scored</th></tr>"
                   + "".join(ledgers) + "</table>"
                   "<p class='small faint'>Ledgers accumulate weekly; bad weeks stay visible.</p>"
                   if ledgers else "")

    body = ('<div class="hero"><h1>Track record</h1><p class="lede">'
            'Every model scored walk-forward against a naive baseline. '
            'No cherry-picking.</p></div>' + "".join(sections) + ledger_html)
    return page_shell("Track record", body, updated=updated)


# ---------------------------------------------------------------- main
def main() -> int:
    from .features import build_features
    from .fit import predict_upcoming

    docs = settings.docs_dir
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "style.css").write_text(CSS)
    updated = date.today().isoformat()

    datas = {lg: LeagueData(lg) for lg in settings.league_order}
    preds = {lg: load_predictions(lg) for lg in settings.league_order}
    feat_pred = {lg: build_features(lg, mode="predict")[0]
                 for lg in settings.league_order}
    players_pl = {}
    p = settings.data_dir / "players_pl.json"
    if p.exists():
        players_pl = json.loads(p.read_text())

    (docs / "index.html").write_text(build_index(datas, preds, updated))

    for league in settings.league_order:
        ld = datas[league]
        ldir = docs / "leagues" / league
        (ldir / "fixtures").mkdir(parents=True, exist_ok=True)
        (ldir / "teams").mkdir(parents=True, exist_ok=True)
        (ldir / "index.html").write_text(build_league(league, ld,
                                                      preds[league], updated))
        pr = preds[league]
        fp = feat_pred[league].set_index("fixture_id") \
            if not feat_pred[league].empty else None
        for _, r in pr.iterrows():
            feats = {}
            if fp is not None and r.fixture_id in fp.index:
                feats = fp.loc[r.fixture_id].to_dict()
            (ldir / "fixtures" / f"{r.fixture_id}.html").write_text(
                build_fixture(league, ld, r, feats, updated))
        for team in sorted(set(ld.fixtures.home) | set(ld.fixtures.away)):
            (ldir / "teams" / f"{slug(team)}.html").write_text(
                build_team(league, ld, team, players_pl, updated))

    (docs / "players.html").write_text(build_players(datas, updated))
    (docs / "track-record.html").write_text(build_track_record(datas, updated))

    n_pages = (1 + len(settings.league_order)
               + sum(len(preds[lg]) for lg in settings.league_order)
               + sum(len(set(datas[lg].fixtures.home) |
                         set(datas[lg].fixtures.away))
                     for lg in settings.league_order) + 2)
    log.info("site_built", pages=n_pages, docs=str(docs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
