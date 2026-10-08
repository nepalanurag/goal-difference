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
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .config import settings
from .logging_setup import get_logger
from .scorer_probs import BUNDESLIGA_CLUB_MAP, normalize_laliga_team
from .team_names import CANONICAL, canonicalize

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
.nav{display:flex;gap:16px;flex-wrap:wrap;font-size:.92em;align-items:center}
.nav a{color:var(--muted)} .nav a:hover{color:var(--text)}
.dropdown{position:relative}
.dropbtn{color:var(--muted);cursor:pointer}
.dropbtn::after{content:" \\25be";font-size:.8em}
.dropdown:hover .dropbtn{color:var(--text)}
.dropdown-content{display:none;position:absolute;top:calc(100% + 10px);left:0;
  background:#0d1117;border:1px solid var(--line);border-radius:8px;
  min-width:180px;padding:6px;z-index:30}
.dropdown:hover .dropdown-content,.dropdown:focus-within .dropdown-content{display:block}
.dropdown-content a{display:block;padding:8px 12px;border-radius:4px}
.dropdown-content a:hover{background:#1a212d}
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
.data-updated{color:var(--faint);font-size:.82em;margin:12px 0 0}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 16px}
.tabbtn{background:var(--panel2);border:1px solid var(--line);color:var(--muted);
  border-radius:6px;padding:6px 14px;cursor:pointer;font-size:.9em;
  font-family:inherit}
.tabbtn:hover{color:var(--text);border-color:var(--muted)}
.tabbtn.active{background:#ffd23f;border-color:#ffd23f;color:#0a0d12;
  font-weight:700}
th.sortable{cursor:pointer;user-select:none}
th.sortable:hover{color:var(--text)}
th.sortable .arrow{font-size:.75em;color:var(--faint)}
.toggle-row{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}
.tgl{background:var(--panel2);border:1px solid var(--line);color:var(--muted);
  border-radius:6px;padding:5px 12px;cursor:pointer;font-size:.85em;
  font-family:inherit}
.tgl:hover{color:var(--text)}
.tgl.active{background:#4da3ff;border-color:#4da3ff;color:#0a0d12;font-weight:700}
"""

# Small vanilla-JS layer: progressive enhancement only. With JS disabled the
# site shows the full tables and the ensemble view everywhere; the JS adds
# tabs, toggles and sorting on top of the rendered HTML.
APP_JS = """
(function () {
  'use strict';

  function on(selector, event, fn) {
    document.querySelectorAll(selector).forEach(function (el) {
      el.addEventListener(event, fn);
    });
  }

  // ---- Sortable tables: click a <th> to sort by that column (toggle asc/desc).
  function cellValue(td) {
    var t = td.textContent.trim().replace('%', '').replace(/,/g, '');
    var n = parseFloat(t);
    return isNaN(n) ? t.toLowerCase() : n;
  }
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var head = table.querySelector('tr');
    if (!head) return;
    var ths = Array.prototype.slice.call(head.querySelectorAll('th'));
    ths.forEach(function (th, idx) {
      th.classList.add('sortable');
      th.title = 'Sort by this column';
      th.setAttribute('tabindex', '0');
      th.addEventListener('click', function () { sortBy(table, ths, idx); });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sortBy(table, ths, idx); }
      });
    });
  });
  function sortBy(table, ths, idx) {
    var asc = ths[idx].getAttribute('data-dir') !== 'asc';
    var rows = Array.prototype.slice.call(table.querySelectorAll('tr')).slice(1);
    rows.sort(function (a, b) {
      var va = cellValue(a.children[idx] || a.cells[idx] || document.createElement('td'));
      var vb = cellValue(b.children[idx] || b.cells[idx] || document.createElement('td'));
      if (va === vb) return 0;
      if (asc) return va < vb ? -1 : 1;
      return va > vb ? -1 : 1;
    });
    rows.forEach(function (r) { table.appendChild(r); });
    ths.forEach(function (t) { t.removeAttribute('data-dir'); t.querySelector('.arrow') &&
      t.querySelector('.arrow').remove(); });
    ths[idx].setAttribute('data-dir', asc ? 'asc' : 'desc');
    var arrow = document.createElement('span');
    arrow.className = 'arrow';
    arrow.textContent = asc ? ' \\u25b2' : ' \\u25bc';
    ths[idx].appendChild(arrow);
  }

  // ---- League tabs: containers holding .league-panel children get a tab bar.
  var LEAGUE_NAMES = {pl: 'Premier League', laliga: 'LaLiga',
    bundesliga: 'Bundesliga', seriea: 'Serie A', ligue1: 'Ligue 1'};
  ['leaderboards', 'backend-rankings'].forEach(function (id) {
    var box = document.getElementById(id);
    if (!box) return;
    var panels = box.querySelectorAll('.league-panel');
    if (!panels.length) return;
    var bar = document.createElement('div');
    bar.className = 'tabs';
    panels.forEach(function (p, i) {
      var key = p.getAttribute('data-league');
      var b = document.createElement('button');
      b.className = 'tabbtn' + (i === 0 ? ' active' : '');
      b.textContent = LEAGUE_NAMES[key] || key;
      b.addEventListener('click', function () {
        panels.forEach(function (q) { q.hidden = q !== p; });
        bar.querySelectorAll('.tabbtn').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
      });
      bar.appendChild(b);
      p.hidden = i !== 0;
    });
    box.insertBefore(bar, box.firstChild);
  });

  // ---- Fixture probability views: Poisson / ML / Ensemble toggle.
  var pv = document.getElementById('probviews');
  if (pv) {
    var views = pv.querySelectorAll('.probview');
    if (views.length > 1) {
      var row = document.createElement('div');
      row.className = 'toggle-row';
      var labels = {poisson: 'Poisson', ml: 'Gradient boosting', ensemble: 'Ensemble'};
      views.forEach(function (v) {
        var key = v.getAttribute('data-view');
        var b = document.createElement('button');
        b.className = 'tgl' + (key === 'ensemble' ? ' active' : '');
        b.textContent = labels[key] || key;
        b.addEventListener('click', function () {
          views.forEach(function (w) { w.hidden = w !== v; });
          row.querySelectorAll('.tgl').forEach(function (x) { x.classList.remove('active'); });
          b.classList.add('active');
        });
        row.appendChild(b);
        v.hidden = key !== 'ensemble';
      });
      pv.insertBefore(row, pv.firstChild);
    }
  }

  // ---- Team pages: Season vs Last-5 toggle for the attack/defense card.
  document.querySelectorAll('.stat-toggle').forEach(function (card) {
    var cells = card.querySelectorAll('[data-stat]');
    if (!cells.length) return;
    var row = document.createElement('div');
    row.className = 'toggle-row';
    [['season', 'Season'], ['last5', 'Last 5']].forEach(function (pair, i) {
      var key = pair[0], label = pair[1];
      var b = document.createElement('button');
      b.className = 'tgl' + (i === 0 ? ' active' : '');
      b.textContent = label;
      b.addEventListener('click', function () {
        cells.forEach(function (c) { c.hidden = c.getAttribute('data-stat') !== key; });
        row.querySelectorAll('.tgl').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
      });
      row.appendChild(b);
    });
    card.insertBefore(row, card.firstChild);
    cells.forEach(function (c) { c.hidden = c.getAttribute('data-stat') !== 'season'; });
  });

  // ---- Home page likely-scorers: league filter.
  var sc = document.getElementById('scorers');
  if (sc) {
    var tbodyRows = sc.querySelectorAll('tr[data-league]');
    var seen = {};
    tbodyRows.forEach(function (r) { seen[r.getAttribute('data-league')] = true; });
    var leagues = Object.keys(seen);
    if (leagues.length > 1) {
      var bar = document.createElement('div');
      bar.className = 'tabs';
      function addFilter(key, label) {
        var b = document.createElement('button');
        b.className = 'tabbtn' + (key === 'all' ? ' active' : '');
        b.textContent = label;
        b.addEventListener('click', function () {
          tbodyRows.forEach(function (r) {
            r.hidden = key !== 'all' && r.getAttribute('data-league') !== key;
          });
          bar.querySelectorAll('.tabbtn').forEach(function (x) { x.classList.remove('active'); });
          b.classList.add('active');
        });
        bar.appendChild(b);
      }
      addFilter('all', 'All leagues');
      leagues.forEach(function (l) { addFilter(l, LEAGUE_NAMES[l] || l); });
      sc.insertBefore(bar, sc.firstChild);
    }
  }
})();
"""


def page_shell(title: str, body: str, league: str | None = None,
               updated: str = "") -> str:
    league_links = "".join(
        f'<a href="{SITE_BASE}/leagues/{s}/">{LEAGUE_NAMES[s]}</a>'
        for s in settings.league_order)
    league_links = "".join(
        f'<a href="{SITE_BASE}/leagues/{s}/">{LEAGUE_NAMES[s]}</a>'
        for s in settings.league_order)
    nav = ('<a href="{BASE}/">Home</a>'
           '<div class="dropdown"><span class="dropbtn" tabindex="0">Leagues</span>'
           f'<div class="dropdown-content">{league_links}</div></div>'
           '<a href="{BASE}/track-record.html">Track record</a>'
           '<a href="{BASE}/methodology.html">Methodology</a>'
           '<a href="{BASE}/model-insights.html">Model insights</a>')
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
<div class="wrap"><p class="data-updated">Data updated {esc(updated)}</p>{body}
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
models, refit weekly &middot; updated {esc(updated)} &middot;
<a href="{SITE_BASE}/methodology.html">How the models work</a></div>
</div><script src="{SITE_BASE}/app.js" defer></script></body></html>"""


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


# ------------------------------------------------- 8.1 player leaderboards
def _leaderboard_rows(league: str) -> tuple[list[dict], str, str]:
    """Top-10 rows for a league: (rows, stat label, note).

    Each row: name, team (canonical name or None), stat, goals, assists.
    PL ranks by FPL form; other leagues by goal involvements, tiebreak fewer
    minutes. Only 90+ minute players qualify (except Bundesliga, whose feed
    publishes no minutes).
    """
    d = settings.data_dir
    if league == "pl":
        pl = json.loads((d / "players_pl.json").read_text())
        ps = [p for p in pl.get("players", []) if (p.get("minutes") or 0) >= 90]
        ps.sort(key=lambda p: float(p.get("form") or 0), reverse=True)
        rows = [{"name": p.get("name"), "team": p.get("team"),
                 "stat": float(p.get("form") or 0), "goals": p.get("goals"),
                 "assists": p.get("assists")} for p in ps[:10]]
        return rows, "Form", "Ranked by FPL form (last 30 days)."
    if league == "laliga":
        data = json.loads(
            (d / "player_rankings_official_laliga.json").read_text())
        ps = [p for p in data.get("players", []) if (p.get("minutes") or 0) >= 90]
        for p in ps:
            p["_inv"] = (p.get("goals") or 0) + (p.get("assists") or 0)
        ps.sort(key=lambda p: (-p["_inv"], p.get("minutes") or 0))
        rows = [{"name": p.get("nickname") or p.get("name"),
                 "team": normalize_laliga_team(p.get("team")),
                 "stat": p["_inv"], "goals": p.get("goals"),
                 "assists": p.get("assists")} for p in ps[:10]]
        return (rows, "G+A",
                "Goal involvements. The feed publishes no assists data, so this is goals.")
    if league == "bundesliga":
        data = json.loads(
            (d / "player_rankings_official_bundesliga.json").read_text())
        agg: dict[str, dict] = {}
        for e in data.get("goals", []):
            a = agg.setdefault(e["player"],
                               {"goals": 0, "assists": 0, "club_id": e.get("club_id")})
            a["goals"] = e.get("value") or 0
        for e in data.get("assists", []):
            a = agg.setdefault(e["player"],
                               {"goals": 0, "assists": 0, "club_id": e.get("club_id")})
            a["assists"] = e.get("value") or 0
        ps = sorted(agg.items(), key=lambda kv: (-(kv[1]["goals"] + kv[1]["assists"]),
                                                 -kv[1]["goals"]))
        rows = [{"name": name, "team": BUNDESLIGA_CLUB_MAP.get(a["club_id"]),
                 "stat": a["goals"] + a["assists"], "goals": a["goals"],
                 "assists": a["assists"]} for name, a in ps[:10]]
        return (rows, "G+A",
                "Goal involvements. The feed publishes no minutes, so no 90-minute filter applies.")
    if league == "seriea":
        data = json.loads(
            (d / "player_rankings_official_seriea.json").read_text())
        ps = [p for p in data.get("players", []) if (p.get("minutes") or 0) >= 90]
        for p in ps:
            p["_inv"] = (p.get("goals") or 0) + (p.get("assists") or 0)
        ps.sort(key=lambda p: (-p["_inv"], p.get("minutes") or 0))
        rows = []
        for p in ps[:10]:
            team = canonicalize(p.get("team") or "", "seriea", source="any")
            if team not in CANONICAL["seriea"]:
                team = p.get("team_short")
            rows.append({"name": p.get("name"), "team": team, "stat": p["_inv"],
                         "goals": p.get("goals"), "assists": p.get("assists")})
        return rows, "G+A", "Goal involvements, tiebreak fewer minutes."
    if league == "ligue1":
        data = json.loads(
            (d / "player_rankings_official_ligue1.json").read_text())
        agg = {}
        for e in data.get("scorers", []) + data.get("assists", []):
            a = agg.setdefault(e["player"], {"goals": 0, "assists": 0,
                                             "minutes": 0, "club": e.get("club")})
            a["goals"] = max(a["goals"], e.get("goals") or 0)
            a["assists"] = max(a["assists"], e.get("assists") or 0)
            a["minutes"] = max(a["minutes"], e.get("minutes") or 0)
        ps = [(n, a) for n, a in agg.items() if (a["minutes"] or 0) >= 90]
        ps.sort(key=lambda kv: (-(kv[1]["goals"] + kv[1]["assists"]),
                                kv[1]["minutes"]))
        rows = [{"name": n, "team": a["club"],
                 "stat": a["goals"] + a["assists"], "goals": a["goals"],
                 "assists": a["assists"]} for n, a in ps[:10]]
        return rows, "G+A", "Goal involvements, tiebreak fewer minutes."
    return [], "", ""


def _leaderboards_html() -> str:
    parts = ['<h2>Leaderboards</h2><p class="small muted">Top 10 per league, '
             'current season only. Premier League ranked by FPL form; other '
             'leagues by goal involvements. 90+ minutes to qualify. '
             'Click a column header to sort.</p><div id="leaderboards">']
    for league in settings.league_order:
        rows, label, note = _leaderboard_rows(league)
        if not rows:
            continue
        trs = []
        for i, r in enumerate(rows, 1):
            team = r["team"]
            if team:
                tcell = (f'<a href="{SITE_BASE}/leagues/{league}/teams/'
                         f'{slug(team)}.html">{esc(team)}</a>')
            else:
                tcell = '<span class="faint">-</span>'
            stat = r["stat"]
            stat_txt = f"{stat:.1f}" if isinstance(stat, float) else str(stat)
            trs.append(
                f"<tr><td class='num'>{i}</td><td>{esc(r['name'])}</td>"
                f"<td>{tcell}</td><td class='num'><b>{stat_txt}</b></td>"
                f"<td class='num'>{dash(r['goals'])}</td>"
                f"<td class='num'>{dash(r['assists'])}</td></tr>")
        parts.append(
            f'<div class="league-panel" data-league="{league}">'
            f"<h3>{LEAGUE_NAMES[league]} &mdash; top 10</h3>"
            f"<p class='small faint' style='margin-top:-.5em'>{esc(note)}</p>"
            f"<table class='sortable'><tr><th class='num'>#</th><th>Player</th><th>Team</th>"
            f"<th class='num'>{esc(label)}</th><th class='num'>G</th>"
            f"<th class='num'>A</th></tr>{''.join(trs)}</table></div>")
    parts.append("</div>")
    return "".join(parts)


# ------------------------------------------------- 8.2 likely scorers
_scorers_cache: pd.DataFrame | None = None


def _load_scorers() -> pd.DataFrame:
    """Cached scorer probabilities for per-fixture 'players to watch'."""
    global _scorers_cache
    if _scorers_cache is None:
        p = settings.data_dir / "scorer_probs.csv"
        _scorers_cache = pd.read_csv(p) if p.exists() else pd.DataFrame()
    return _scorers_cache


def watch_html(fixture_id: str, n: int = 3) -> str:
    """'Players to watch' line for a fixture card, from scorer probabilities."""
    sc = _load_scorers()
    if sc.empty:
        return ""
    top = sc[sc.fixture_id == fixture_id].sort_values("prob", ascending=False).head(n)
    if top.empty:
        return ""
    items = ", ".join(f"{esc(r.player)} <span class='muted'>{r.prob:.0%}</span>"
                      for _, r in top.iterrows())
    return (f"<div class='small' style='margin-top:6px'>"
            f"<span class='muted'>Players to watch:</span> {items}</div>")


def scorers_section(scorers: pd.DataFrame) -> str:
    """Top-15 'Likely scorers this week' table with model inputs shown."""
    if scorers is None or scorers.empty:
        return ""
    top = scorers.sort_values("prob", ascending=False).head(15)
    trs = []
    for _, r in top.iterrows():
        league = str(r.fixture_id).split("-")[0]
        tcell = (f'<a href="{SITE_BASE}/leagues/{league}/teams/{slug(r.team)}.html">'
                 f'{esc(r.team)}</a>')
        fcell = (f'<a class="fixlink" href="{SITE_BASE}/leagues/{league}/fixtures/'
                 f'{r.fixture_id}.html">{esc(r.home)} v {esc(r.away)}</a>')
        trs.append(
            f"<tr data-league='{esc(league)}'><td>{esc(r.player)}</td><td>{tcell}</td><td>{fcell}</td>"
            f"<td class='num'><b>{r.prob:.0%}</b></td>"
            f"<td class='num'>{r.per90:.2f}</td>"
            f"<td class='num'>{r.x_minutes:.0f}</td>"
            f"<td class='num'>{r.team_xg:.2f}</td></tr>")
    return ("""<div id="scorers"><h2>Likely scorers this week</h2>
<p class="small muted">Anytime-scorer probability = 1 - exp(-X), where X comes from
the player's shrunk goals-per-90, expected minutes, and the team's model xG for the
fixture. Inputs shown. Model estimates, not betting advice. Bundesliga excluded:
its feed publishes no minutes.</p>
<table class="sortable"><tr><th>Player</th><th>Team</th><th>Fixture</th><th class="num">Prob</th>
<th class="num">Per 90</th><th class="num">xMin</th><th class="num">Team xG</th></tr>"""
            + "".join(trs) + "</table></div>")


# ------------------------------------------------- 8.3 team depth
_depth_cache: dict[str, dict[str, dict]] = {}


def _trend_arrow(l5: float, season: float,
                 lower_is_better: bool = False) -> tuple[str, str]:
    if abs(l5 - season) < 0.005:
        return "\u2192", "muted"
    up = l5 > season
    good = (not up) if lower_is_better else up
    return ("\u2191" if up else "\u2193"), ("positive" if good else "negative")


def team_depth_data(ld: LeagueData) -> dict[str, dict]:
    """Per-team depth numbers for the live season (cached per league).

    Opposition-adjusted PPG reweights each finished game by the opponent's
    final-season PPG (proxy for opponent strength at the time, which is not
    stored). Expected points come from the fitted ensemble's pre-match 1X2 on
    finished fixtures (in-sample): the prediction ledgers hold no scored rows
    yet, so there is nothing to join against.
    """
    if ld.league in _depth_cache:
        return _depth_cache[ld.league]
    out: dict[str, dict] = {}
    live = ld.finished[ld.finished.season == settings.live_season]
    if not live.empty:
        table = ld.table()
        ppg = {t: (pts / max(p, 1)) for t, pts, p in
               zip(table.team, table.pts, table.p)}
        league_mean = sum(ppg.values()) / max(len(ppg), 1)
        for team in sorted(set(live.home) | set(live.away)):
            games = live[(live.home == team) | (live.away == team)]
            pts = 0.0
            wpts = 0.0
            wsum = 0.0
            for _, r in games.iterrows():
                is_home = r.home == team
                hg, ag = r.home_goals, r.away_goals
                if hg == ag:
                    p = 1
                elif (hg > ag and is_home) or (ag > hg and not is_home):
                    p = 3
                else:
                    p = 0
                opp = r.away if is_home else r.home
                w = ppg.get(opp, league_mean) / league_mean if league_mean else 1.0
                pts += p
                wpts += p * w
                wsum += w
            n = len(games)
            out[team] = {"played": n, "raw_ppg": pts / n,
                         "adj_ppg": wpts / wsum if wsum else 0.0,
                         "actual_pts": int(pts)}
        try:
            from .fit import blend_ensemble, load_models
            poisson_model, ml_model, feature_cols, _ = load_models(ld.league)
            feats = ld.features[ld.features["season"].astype(str)
                                == str(settings.live_season)]
            feats = feats.drop_duplicates("fixture_id", keep="last")
            if not feats.empty:
                p_dc = np.asarray(
                    poisson_model.predict_proba_df(feats, feature_cols))
                p_ml = np.asarray(ml_model.predict_proba(feats[feature_cols]))
                p_ens = blend_ensemble(p_dc, p_ml)
                # column order is (away, draw, home); see predict_upcoming
                for (_, r), probs in zip(feats.iterrows(), p_ens):
                    pa, pd_, ph = float(probs[0]), float(probs[1]), float(probs[2])
                    home_exp = out.setdefault(r.home, {}).get("exp_pts", 0.0) \
                        + 3 * ph + pd_
                    away_exp = out.setdefault(r.away, {}).get("exp_pts", 0.0) \
                        + 3 * pa + pd_
                    out[r.home]["exp_pts"] = round(home_exp, 1)
                    out[r.away]["exp_pts"] = round(away_exp, 1)
        except Exception as exc:  # noqa: BLE001 - depth blocks degrade gracefully
            log.warning("depth_expected_points_failed", league=ld.league,
                        error=str(exc)[:160])
    _depth_cache[ld.league] = out
    return out


def _depth_html(team: str, f: dict, dd: dict) -> str:
    """The three 8.3 depth blocks for a team page. Empty when no data."""
    if not dd.get("played"):
        return ""
    raw, adj = dd["raw_ppg"], dd["adj_ppg"]
    if adj < raw - 0.05:
        sched = "softer schedule so far"
    elif adj > raw + 0.05:
        sched = "tougher schedule so far"
    else:
        sched = "schedule about average"
    actual, exp = dd["actual_pts"], dd.get("exp_pts")
    if exp is not None:
        diff = actual - exp
        cls = "positive" if diff > 0.5 else ("negative" if diff < -0.5 else "muted")
        exp_rows = (f"<tr><td class='muted'>Actual points</td>"
                    f"<td class='num'><b>{actual}</b></td></tr>"
                    f"<tr><td class='muted'>Expected points</td>"
                    f"<td class='num'>{exp:.1f}</td></tr>"
                    f"<tr><td class='muted'>Diff</td>"
                    f"<td class='num'><span class='{cls}'>{diff:+.1f}</span></td></tr>")
    else:
        exp_rows = (f"<tr><td class='muted'>Actual points</td>"
                    f"<td class='num'><b>{actual}</b></td></tr>")
    gf, gf5 = f.get("gf_pg", 0), f.get("gf_pg_l5", 0)
    ga, ga5 = f.get("ga_pg", 0), f.get("ga_pg_l5", 0)
    a_arrow, a_cls = _trend_arrow(gf5, gf)
    d_arrow, d_cls = _trend_arrow(ga5, ga, lower_is_better=True)
    return f"""<h2>Depth check</h2><div class="grid g3">
<div class="card"><h3>Opposition-adjusted form</h3><table class="small">
<tr><td class="muted">Raw PPG</td><td class="num">{raw:.2f}</td></tr>
<tr><td class="muted">Adjusted PPG</td><td class="num"><b>{adj:.2f}</b></td></tr>
</table><p class="small faint" style="margin-bottom:0">Each game reweighted by
opponent strength (final PPG as proxy): {sched}.</p></div>
<div class="card"><h3>Expected points</h3><table class="small">{exp_rows}</table>
<p class="small faint" style="margin-bottom:0">Expected points from the fitted
ensemble's pre-match 1X2 (in-sample).</p></div>
<div class="card"><h3>Attack / defense trend</h3><table class="small">
<tr><td class="muted">Scored / game</td><td class="num">{gf:.2f}</td>
<td class="muted">last-5</td><td class="num">{gf5:.2f}
<span class="{a_cls}">{a_arrow}</span></td></tr>
<tr><td class="muted">Conceded / game</td><td class="num">{ga:.2f}</td>
<td class="muted">last-5</td><td class="num">{ga5:.2f}
<span class="{d_cls}">{d_arrow}</span></td></tr>
</table><p class="small faint" style="margin-bottom:0">Arrow compares the last 5
games to the season rate.</p></div>
</div>"""


# ---------------------------------------------------------------- index page
def build_index(datas: dict[str, LeagueData],
                preds: dict[str, pd.DataFrame],
                scorers: pd.DataFrame, updated: str) -> str:
    cards = []
    for league in settings.league_order:
        ld = datas[league]
        t = ld.table()
        leader = t.iloc[0]
        p_title = ""
        if not ld.odds.empty:
            row = ld.odds[ld.odds.team == leader.team]
            if not row.empty:
                p_title = f"Title: {pct(row.iloc[0].p_title)}"
        n_up = len(ld.upcoming)
        cards.append(f"""<div class="card">
<h3 style="color:{LEAGUE_ACCENT[league]}">{LEAGUE_NAMES[league]}</h3>
<div class="kpi">{esc(leader.team)}<br><small>{leader.pts} pts after {leader.p}</small></div>
<div class="small muted">{p_title}</div>
<div style="margin-top:10px"><a href="{SITE_BASE}/leagues/{league}/">League hub &rarr;</a></div>
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
<div style="font-size:1.2em"><a class="fixlink" href="{SITE_BASE}/leagues/{league}/fixtures/{r.fixture_id}.html">
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
<h2>Key matchups</h2>{matchup_html}
{scorers_section(scorers)}"""
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
            f"<td><a href=\"{SITE_BASE}/leagues/{league}/teams/{slug(r.team)}.html\">"
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
href="{SITE_BASE}/leagues/{league}/fixtures/{r.fixture_id}.html">{esc(r.home)} v {esc(r.away)}</a></div>
{prob_bar(r.p_home_ens, r.p_draw_ens, r.p_away_ens)}
{prob_legend(r.home, r.away)}
<div class="small muted" style="margin-top:6px">xG {r.xg_home:.2f} - {r.xg_away:.2f}</div>
{watch_html(r.fixture_id)}
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
and this matchday's fixtures with ensemble probabilities.</p>
<p><a href="{SITE_BASE}/players.html#{league}">Players &rarr;</a></p></div>
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

    probs = f"""<div class="card" id="probviews"><h3>Model probabilities</h3>
<table><tr><th></th><th class="num">Home</th><th class="num">Draw</th><th class="num">Away</th></tr>
<tr><td>Poisson</td><td class="num">{pct(row.p_home_poisson)}</td>
<td class="num">{pct(row.p_draw_poisson)}</td><td class="num">{pct(row.p_away_poisson)}</td></tr>
<tr><td>Gradient boosting</td><td class="num">{pct(row.p_home_ml)}</td>
<td class="num">{pct(row.p_draw_ml)}</td><td class="num">{pct(row.p_away_ml)}</td></tr>
<tr><td><b>Ensemble</b></td><td class="num"><b>{pct(row.p_home_ens)}</b></td>
<td class="num"><b>{pct(row.p_draw_ens)}</b></td><td class="num"><b>{pct(row.p_away_ens)}</b></td></tr>
</table>
<div class="probview" data-view="poisson" hidden>
{prob_bar(row.p_home_poisson, row.p_draw_poisson, row.p_away_poisson)}
<p class="small muted" style="margin-top:4px">Poisson (Dixon-Coles) only.</p></div>
<div class="probview" data-view="ml" hidden>
{prob_bar(row.p_home_ml, row.p_draw_ml, row.p_away_ml)}
<p class="small muted" style="margin-top:4px">Gradient boosting only.</p></div>
<div class="probview" data-view="ensemble">
{prob_bar(row.p_home_ens, row.p_draw_ens, row.p_away_ens)}
{prob_legend(home, away)}
<p class="small muted">Expected goals: <span class="mono">{row.xg_home:.2f} - {row.xg_away:.2f}</span>.
Each row sums to 100%.</p></div></div>"""

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
<h2>Prediction</h2><div class="grid g2">{probs}{expect}</div>
<h2>Players to watch</h2><div class="card">{watch_html(row.fixture_id, n=5) or "<p class='muted'>No scorer data for this fixture.</p>"}</div>"""
    return page_shell(f"{home} v {away}", body, league=league, updated=updated)


# ---------------------------------------------------------------- team page
def build_team(league: str, ld: LeagueData, team: str,
               players_pl: dict, depth: dict[str, dict], updated: str) -> str:
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
                    f"<a href='{SITE_BASE}/leagues/{league}/fixtures/{r0.fixture_id}.html'>preview &rarr;</a></p></div>")
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

    # Squad panel (PL only, from FPL): this team's in-form players.
    squad = ""
    if league == "pl" and players_pl:
        team_players = sorted(
            [p for p in players_pl.get("players", [])
             if p.get("team") == team and (p.get("minutes") or 0) >= 90],
            key=lambda p: float(p.get("form") or 0), reverse=True)[:6]
        if team_players:
            rows = "".join(
                f"<div class='small'>{esc(p.get('name', ''))} "
                f"<span class='muted'>{esc(p.get('position', ''))}</span> "
                f"<span class='num'><b>{p.get('form', '')}</b> form</span></div>"
                for p in team_players)
            squad = (f"<h2>Squad watch</h2><div class='card'><h3>{esc(team)} in form</h3>{rows}"
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
<div class="card stat-toggle"><h3>Attack / defense</h3><table class="small">
<tr><td class="muted">Scored / game</td><td class="num" data-stat="season">{f.get('gf_pg', 0):.2f}</td>
<td class="muted" data-stat="last5">last-5</td><td class="num" data-stat="last5">{f.get('gf_pg_l5', 0):.2f}</td></tr>
<tr><td class="muted">Conceded / game</td><td class="num" data-stat="season">{f.get('ga_pg', 0):.2f}</td>
<td class="muted" data-stat="last5">last-5</td><td class="num" data-stat="last5">{f.get('ga_pg_l5', 0):.2f}</td></tr>
<tr><td class="muted">Shot dominance</td><td class="num" data-stat="season">{f.get('shot_diff_pg', 0):+.1f}</td>
<td class="muted" data-stat="last5">shots on target</td><td class="num" data-stat="last5">{f.get('sot_pg', 0):.1f}</td></tr>
<tr><td class="muted">Clean sheets</td><td class="num" data-stat="season">{pct(f.get('cs_rate', 0))}</td>
<td class="muted" data-stat="last5">Failed to score</td><td class="num" data-stat="last5">{pct(f.get('fts_rate', 0))}</td></tr>
<tr><td class="muted">Discipline</td><td class="num" data-stat="season">{f.get('fouls_pg', 0):.1f} fouls/g</td>
<td class="muted" data-stat="last5">cards</td><td class="num" data-stat="last5">{f.get('cards_pg', 0):.1f}/g</td></tr>
</table></div></div>
<div class="grid g2">{next_opp}{difficulty}</div>
{_depth_html(team, f, depth.get(team, {}) if depth else {})}
<div class="grid g2">{euro_html}{avail}</div>
{squad}"""
    return page_shell(team, body, league=league, updated=updated)


def ordinal(n: int) -> str:
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# ---------------------------------------------------------------- players
def build_players(datas: dict[str, LeagueData], scorers: pd.DataFrame,
                  updated: str) -> str:
    d = settings.data_dir
    sections = [_leaderboards_html(), scorers_section(scorers)]

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
        sections.append(f"""<div class="league-panel" data-league="pl">
<h2 id="pl">Premier League &mdash; form watch</h2>
<p class="small muted">Source: FPL API (unofficial). Form = average points over the last 30 days.
Click a column header to sort.</p>
<div class="grid g2"><div class="card"><h3>In-form XI</h3>{xi_html or '<p class="muted">-</p>'}</div>
<div class="card"><h3>Risers this week</h3>{risers or '<p class="muted">-</p>'}</div></div>
<table class="sortable"><tr><th>Player</th><th>Team</th><th>Pos</th><th class="num">Form</th>
<th class="num">Pts</th><th class="num">G</th><th class="num">A</th>
<th class="num">Min</th><th class="num">ICT</th><th class="num">Cost</th>
<th class="num">Pts/m</th></tr>{rows}</table></div>""")

    # Other leagues: official backend rankings.
    backend_labels = {
        "laliga": ("LaLiga", "LaLiga official data backend (apim.laliga.com)"),
        "bundesliga": ("Bundesliga", "Bundesliga official Firebase backend"),
        "seriea": ("Serie A", "Serie A official data backend (api-sdp.legaseriea.it)"),
        "ligue1": ("Ligue 1", "Ligue 1 official backend (ma-api.ligue1.fr)"),
    }
    backend_sections = ['<div id="backend-rankings">']
    for league, (name, source) in backend_labels.items():
        p = d / f"player_rankings_official_{league}.json"
        if not p.exists():
            backend_sections.append(f"<h2>{name}</h2><p class='muted small'>"
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
        backend_sections.append(f"""<div class="league-panel" data-league="{league}">
<h2 id="{league}">{name} &mdash; current season</h2>
<p class="small muted">Source: {esc(source)} (unofficial feed, no SLA).
Click a column header to sort.</p>
<table class="sortable"><tr><th>Player</th><th>Team</th><th class="num">Goals</th>
<th class="num">Assists</th><th class="num">Apps/Min</th></tr>{rows}</table></div>""")
    backend_sections.append("</div>")
    sections.append("".join(backend_sections))

    # Note: data/topscorers_2425.json (last season) is kept in the repo as a
    # labeled baseline for modeling, but per Anurag's rule the site only ever
    # shows current-season data, so it is not rendered here.

    body = ('<div class="hero"><h1>Players</h1><p class="lede">Who is in form, '
            'per league, each source labeled.</p></div>' + "".join(sections))
    return page_shell("Players", body, updated=updated)


# ------------------------------------------------- 8.7 calibration buckets
def _calibration_html() -> str:
    """Per-league calibration-by-confidence-bucket tables."""
    d = settings.data_dir
    parts = ['<h2>Calibration</h2><p class="small muted">Walk-forward ensemble '
             'probabilities grouped by confidence bucket, across all three '
             'outcomes (home, draw, away). When the model is calibrated, the '
             'observed rate tracks the predicted mean.</p>']
    for league in settings.league_order:
        p = d / f"calibration_{league}.json"
        if not p.exists():
            continue
        cal = json.loads(p.read_text())
        trs = []
        for b in cal.get("buckets", []):
            mp = b.get("mean_pred")
            ob = b.get("observed_rate")
            n = b.get("n", 0)
            mp_txt = f"{mp:.3f}" if mp is not None else "-"
            ob_txt = f"{ob:.3f}" if ob is not None else "-"
            trs.append(f"<tr><td class='num'>{b['lo']:.1f}-{b['hi']:.1f}</td>"
                       f"<td class='num'>{mp_txt}</td>"
                       f"<td class='num'><b>{ob_txt}</b></td>"
                       f"<td class='num muted'>{n:,}</td></tr>")
        ver = esc(cal.get("model_version", ""))
        n = cal.get("n_predictions", 0)
        parts.append(
            f"<h3>{LEAGUE_NAMES[league]}</h3>"
            f"<p class='small faint' style='margin-top:-.5em'>{n:,} outcome "
            f"predictions, walk-forward, model {ver}.</p>"
            f"<table><tr><th class='num'>Bucket</th>"
            f"<th class='num'>Predicted mean</th>"
            f"<th class='num'>Observed rate</th>"
            f"<th class='num'>Count</th></tr>{''.join(trs)}</table>")
    return "".join(parts)


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
            'No cherry-picking.</p></div>' + "".join(sections)
            + _calibration_html() + ledger_html)
    return page_shell("Track record", body, updated=updated)


# ---------------------------------------------------------------- model insights
def _freq_bar(freq: float) -> str:
    w = int(round(freq * 100))
    return (f'<div style="background:#eee;height:8px;width:120px;'
            f'display:inline-block;vertical-align:middle">'
            f'<div style="background:#1a7f4b;height:8px;width:{w}%"></div></div>'
            f' <span class="num">{w}%</span>')


def build_model_insights(datas: dict[str, "LeagueData"], updated: str) -> str:
    """Per-league PAM feature-selection tables and the PAM-vs-full verdict."""
    from .pam_select import GROUP_LABELS, GROUP_ORDER
    sections = []
    method = ('<p class="small muted">Feature groups are tested against '
              'row-permuted decoy copies of themselves: each group is fitted '
              'alongside 5 shuffled copies, and it "wins" a round when its '
              'real features carry more model importance than every copy. '
              'A group is kept when it wins at least 60% of 20 rounds. '
              'Stability is the Jaccard similarity of the kept sets on two '
              'halves of the data. The kept set trains the final ML model '
              'only if it beats the full feature set walk-forward; otherwise '
              'the full set stays.</p>')
    for league in settings.league_order:
        pam_path = settings.data_dir / f"pam_selection_{league}.json"
        fm = ((datas[league].params or {}).get("feature_mask") or {})
        if not pam_path.exists():
            sections.append(f"<h2>{LEAGUE_NAMES[league]}</h2>"
                            "<p class='muted'>Feature selection not run for "
                            "this league yet.</p>")
            continue
        pam = json.loads(pam_path.read_text())
        freqs = pam.get("selection_frequency", {})
        groups = pam.get("groups", {})
        selected = set(pam.get("selected_groups", []))
        rows = ""
        for g in GROUP_ORDER:
            if g not in groups:
                continue
            f = freqs.get(g, 0.0)
            mark = "yes" if g in selected else "no"
            rows += (f"<tr><td>{esc(GROUP_LABELS.get(g, g))}</td>"
                     f"<td class='num'>{len(groups[g])}</td>"
                     f"<td>{_freq_bar(f)}</td>"
                     f"<td>{mark}</td></tr>")
        jac = pam.get("jaccard_stability")
        stab = (f"<p class='small'>Selection stability (Jaccard, two data "
                f"halves): <b>{jac:.2f}</b>.</p>" if jac is not None else "")
        cmp_ = fm.get("pam_compare") or {}
        if cmp_:
            verdict = ("The selected features won walk-forward and train the "
                       "final model." if fm.get("source") == "pam"
                       else "The full feature set won walk-forward, so it "
                            "trains the final model.")
            comp = (f"<p class='small'>Walk-forward log-loss, xgb_tiny: "
                    f"selected features <b>{cmp_['pam_logloss']:.4f}</b> vs "
                    f"full set <b>{cmp_['full_logloss']:.4f}</b>. {verdict}</p>")
        else:
            comp = ("<p class='small faint'>PAM-vs-full comparison not run "
                    "yet (needs a refit with the selection file present).</p>")
        sections.append(f"<h2>{LEAGUE_NAMES[league]}</h2>"
                        f"<table><tr><th>Feature group</th>"
                        f"<th class='num'>Features</th>"
                        f"<th>Selection frequency</th><th>Kept</th></tr>"
                        f"{rows}</table>{stab}{comp}")
    body = ('<div class="hero"><h1>Model insights</h1>'
            '<p class="lede">Which feature groups the model actually keeps, '
            'and whether the smaller set earns its place.</p></div>'
            + method + "".join(sections)
            + f'<p class="small"><a href="{SITE_BASE}/track-record.html">'
              'Track record &rarr;</a></p>')
    return page_shell("Model insights", body, updated=updated)


# ------------------------------------------------- 8.7 methodology
def build_methodology(datas: dict[str, "LeagueData"], updated: str) -> str:
    """Model, inputs, per-league params, evaluation, honest limitations."""
    from .pam_select import GROUP_LABELS, GROUP_ORDER

    # Per-league Dixon-Coles params.
    dc_rows = []
    ens_w = {}
    ml_cfgs = {}
    for league in settings.league_order:
        p = (datas[league].params or {})
        dc = p.get("dc", {})
        dc_rows.append(
            f"<tr><td>{LEAGUE_NAMES[league]}</td>"
            f"<td class='num'>{dc.get('xi', 0):.4f}</td>"
            f"<td class='num'>{dc.get('home_adv', 0):.3f}</td>"
            f"<td class='num'>{dc.get('rho', 0):+.3f}</td>"
            f"<td class='num muted'>{dc.get('n_matches', 0):,}</td></tr>")
        if league == "pl":
            ens_w = p.get("ensemble_weights", {})
        ml_cfgs[LEAGUE_NAMES[league]] = p.get("chosen_ml", "gradient boosting")
    ml_note = ", ".join(f"{lg}: {esc(cfg)}" for lg, cfg in ml_cfgs.items())
    dc_table = (f"<table><tr><th>League</th>"
                f"<th class='num'>Time decay (xi)</th>"
                f"<th class='num'>Home advantage</th>"
                f"<th class='num'>Rho</th>"
                f"<th class='num'>Matches fitted</th></tr>"
                f"{''.join(dc_rows)}</table>")

    # Feature families.
    feat_items = "".join(
        f"<li>{esc(GROUP_LABELS[g])}</li>" for g in GROUP_ORDER
        if g in GROUP_LABELS)

    # Evaluation: walk-forward log-loss, Brier, RPS for the ensemble,
    # plus the de-vigged market benchmark.
    eval_rows = []
    notes = []
    for league in settings.league_order:
        wf = (datas[league].params or {}).get("walkforward", {})
        ens = wf.get("ensemble", {})
        odds = wf.get("odds", {})
        mkt = ""
        if odds:
            ll_o, ll_e = odds.get("logloss"), ens.get("logloss")
            if ll_o is not None and ll_e is not None:
                mkt = (f"<td class='num'>{ll_o:.4f}</td>"
                       f"<td class='num'>{odds.get('rps', 0):.4f}</td>")
                if ll_o < ll_e:
                    notes.append(
                        f"In {LEAGUE_NAMES[league]} the de-vigged market "
                        f"odds beat the ensemble on walk-forward log-loss "
                        f"({ll_o:.4f} vs {ll_e:.4f}).")
            else:
                mkt = "<td class='num'>-</td><td class='num'>-</td>"
        eval_rows.append(
            f"<tr><td>{LEAGUE_NAMES[league]}</td>"
            f"<td class='num'>{ens.get('logloss', 0):.4f}</td>"
            f"<td class='num'>{ens.get('brier', 0):.4f}</td>"
            f"<td class='num'>{ens.get('rps', 0):.4f}</td>"
            f"<td class='num'>{pct(ens.get('accuracy', 0))}</td>{mkt}</tr>")
    eval_table = (f"<table><tr><th>League</th>"
                  f"<th class='num'>Ensemble log-loss</th>"
                  f"<th class='num'>Brier</th><th class='num'>RPS</th>"
                  f"<th class='num'>Accuracy</th>"
                  f"<th class='num'>Market log-loss</th>"
                  f"<th class='num'>Market RPS</th></tr>"
                  f"{''.join(eval_rows)}</table>")

    w_ml = ens_w.get("ml", 0.6) if ens_w else 0.6
    w_dc = ens_w.get("dc", 0.4) if ens_w else 0.4
    body = f"""<div class="hero"><h1>Methodology</h1>
<p class="lede">How the predictions are made, what goes in, how they score,
and where they fall short.</p></div>

<h2>The model</h2>
<div class="card"><p style="margin-top:0">Each league is fitted separately.
Two models run side by side and are blended into one headline probability:</p>
<ul>
<li><b>Dixon-Coles Poisson.</b> A per-league Poisson goal model with a time
decay parameter (recent matches weigh more), an estimated home advantage,
and a rho term adjusting for correlated low scores. Fitted by maximum
likelihood on the finished fixtures.</li>
<li><b>Gradient boosting.</b> Trained on the selected feature set from
permutation-assisted selection (PAM), which keeps only feature groups that
beat shuffled decoy copies. Config per league: {ml_note}.</li>
<li><b>Ensemble.</b> The headline probability is {w_ml:g} x ML plus
{w_dc:g} x Dixon-Coles. The weights are fixed, not tuned per matchday.</li>
</ul></div>

<h2>Inputs</h2>
<div class="card"><ul style="margin:0">{feat_items}</ul>
<p class="small muted" style="margin-bottom:0">Team news: full injury data for
the PL via FPL; other leagues use absences detected from lineups, labeled
"reason unconfirmed". Forecasts freeze before kickoff; ledgers keep the
misses.</p></div>

<h2>Dixon-Coles parameters</h2>
{dc_table}
<p class="small muted">Xi is the per-day time decay; home advantage and rho
are on the goal scale. Fitted on all finished fixtures in the data window.</p>

<h2>Evaluation</h2>
{eval_table}
<p class="small muted">Walk-forward (time-series split) on all finished
fixtures. Lower is better for log-loss, Brier and RPS. The market benchmark
is de-vigged closing odds: the raw home/draw/away odds with the bookmaker
margin removed, scored on the same walk-forward splits. See the
<a href="{{BASE}}/track-record.html">track record</a> page for per-model
tables and calibration by confidence bucket.</p>

<h2>Honest limitations</h2>
<div class="limit"><ul style="margin:0">
<li><b>The market is a hard benchmark.</b>
{" ".join(esc(n) for n in notes) if notes else "The de-vigged market odds score close to the ensemble on most leagues."}
Odds compilers see team sheets, weather and late money; this model does not.</li>
<li><b>Feature selection is unstable.</b> PAM selection run on two halves of
the data agrees on a Jaccard similarity of 0.0 for every league. The selected
set still beat the full set walk-forward for most leagues, but treat the
"kept" groups as one draw, not the truth.</li>
<li><b>Probabilities are estimates.</b> A 70% probability means the model
expects that outcome 7 times in 10, not that it knows which. These numbers
are not betting advice.</li>
</ul></div>"""
    return page_shell("Methodology", body, updated=updated)


# ---------------------------------------------------------------- main
def main() -> int:
    from .features import build_features
    from .fit import predict_upcoming

    docs = settings.docs_dir
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "style.css").write_text(CSS)
    (docs / "app.js").write_text(APP_JS.strip() + "\n")
    updated = date.today().isoformat()

    datas = {lg: LeagueData(lg) for lg in settings.league_order}
    preds = {lg: load_predictions(lg) for lg in settings.league_order}
    feat_pred = {lg: build_features(lg, mode="predict")[0]
                 for lg in settings.league_order}
    players_pl = {}
    p = settings.data_dir / "players_pl.json"
    if p.exists():
        players_pl = json.loads(p.read_text())

    from .scorer_probs import compute_scorer_probs
    scorers = compute_scorer_probs(preds)
    (settings.data_dir / "scorer_probs.csv").write_text(
        scorers.to_csv(index=False))
    log.info("scorer_probs_written", rows=len(scorers))
    depth = {lg: team_depth_data(datas[lg]) for lg in settings.league_order}

    (docs / "index.html").write_text(build_index(datas, preds, scorers, updated))

    for league in settings.league_order:
        ld = datas[league]
        ldir = docs / "leagues" / league
        for sub in ("fixtures", "teams"):
            subdir = ldir / sub
            subdir.mkdir(parents=True, exist_ok=True)
            # Drop pages from older fixture sets (e.g. superseded schedule
            # reconstructions); without this, stale impossible fixtures
            # accumulate on the live site.
            for stale in subdir.glob("*.html"):
                stale.unlink()
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
        live_teams = ld.fixtures[ld.fixtures.season == settings.live_season]
        for team in sorted(set(live_teams.home) | set(live_teams.away)):
            (ldir / "teams" / f"{slug(team)}.html").write_text(
                build_team(league, ld, team, players_pl, depth[league], updated))

    (docs / "players.html").write_text(build_players(datas, scorers, updated))
    (docs / "track-record.html").write_text(build_track_record(datas, updated))
    (docs / "methodology.html").write_text(build_methodology(datas, updated))
    (docs / "model-insights.html").write_text(
        build_model_insights(datas, updated))

    n_pages = (1 + len(settings.league_order)
               + sum(len(preds[lg]) for lg in settings.league_order)
               + sum(len(set(datas[lg].fixtures.home) |
                         set(datas[lg].fixtures.away))
                     for lg in settings.league_order) + 2)
    log.info("site_built", pages=n_pages, docs=str(docs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
