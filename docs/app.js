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
    arrow.textContent = asc ? ' \u25b2' : ' \u25bc';
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
