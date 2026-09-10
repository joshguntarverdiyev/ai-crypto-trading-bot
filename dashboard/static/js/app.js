/*
 * P9 Trading Monitor — read-only SPA (vanilla, no build).
 *
 * Consumes ONLY the read-only dashboard API (/api/...). It never calls any control
 * endpoint, never places/modifies a trade, and holds no credentials. Each panel
 * fetches independently so one failing endpoint degrades only that panel.
 */
(function () {
  "use strict";

  var API = "/api";

  // ---------------------------------------------------------------- data sources
  var SOURCES = {
    runs:       { interval: 5000,  url: function () { return API + "/paper/runs?limit=25"; } },
    health:     { interval: 5000,  perRun: true, url: function (id) { return API + "/paper/health?run_id=" + id; } },
    portfolio:  { interval: 15000, perRun: true, url: function (id) { return API + "/paper/portfolio?run_id=" + id; } },
    positions:  { interval: 15000, perRun: true, url: function (id) { return API + "/paper/positions?run_id=" + id; } },
    decisions:  { interval: 15000, perRun: true, url: function (id) { return API + "/paper/decisions?run_id=" + id + "&limit=60"; } },
    claude:     { interval: 15000, perRun: true, url: function (id) { return API + "/paper/claude?run_id=" + id + "&limit=40"; } },
    news:       { interval: 15000, perRun: true, url: function (id) { return API + "/paper/news?run_id=" + id + "&limit=40"; } },
    risk:       { interval: 15000, perRun: true, url: function (id) { return API + "/paper/risk?run_id=" + id + "&limit=40"; } },
    events:     { interval: 20000, perRun: true, url: function (id) { return API + "/paper/events?run_id=" + id + "&limit=60"; } },
    orders:     { interval: 20000, perRun: true, url: function (id) { return API + "/paper/orders?run_id=" + id + "&limit=60"; } },
    fills:      { interval: 20000, perRun: true, url: function (id) { return API + "/paper/fills?run_id=" + id + "&limit=60"; } },
    equity:     { interval: 15000, perRun: true, url: function (id) { return API + "/paper/equity_curve?run_id=" + id; } },
    metrics:    { interval: 30000, perRun: true, url: function (id) { return API + "/paper/metrics?run_id=" + id; } },
    validation: { interval: 60000, perRun: true, url: function (id) { return API + "/paper/validation?run_id=" + id; } },
    universe:   { interval: 0,     perRun: true, url: function (id) { return API + "/paper/universe?run_id=" + id; } },
    backtests:  { interval: 60000, url: function () { return API + "/backtests?limit=25"; } },
    shadowRuns: { interval: 60000, url: function () { return API + "/shadow/runs?limit=25"; } },
    shadowDec:  { interval: 60000, url: function () { return API + "/shadow/decisions?limit=50"; } },
  };

  var cache = {}, fetchAt = {};
  var state = { runId: null, run: null };
  var dirty = false, chartInst = null;

  // ---------------------------------------------------------------- dom + format
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
      if (k === "class") e.className = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    if (kids != null) (Array.isArray(kids) ? kids : [kids]).forEach(function (c) {
      if (c == null) return;
      e.appendChild((typeof c === "string" || typeof c === "number") ? document.createTextNode(String(c)) : c);
    });
    return e;
  }
  function na() { return el("span", { class: "na" }, "N/A"); }
  function pf(v) { var f = parseFloat(v); return isFinite(f) ? f : null; }
  function money(v) { var f = pf(v); return f == null ? null : f.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function pct(frac, dp) { var f = pf(frac); return f == null ? null : (f * 100).toFixed(dp == null ? 2 : dp) + "%"; }
  function shortId(id) { return id ? String(id).slice(0, 8) + "…" : "—"; }
  function parseTs(iso) { if (!iso) return null; var s = String(iso); if (!/[zZ]|[+\-]\d\d:?\d\d$/.test(s)) s += "Z"; var d = new Date(s); return isNaN(d.getTime()) ? null : d; }
  function agoMs(ms) { if (!ms) return "—"; var s = Math.max(0, (Date.now() - ms) / 1000); if (s < 60) return Math.floor(s) + "s ago"; if (s < 3600) return Math.floor(s / 60) + "m ago"; if (s < 86400) return Math.floor(s / 3600) + "h ago"; return Math.floor(s / 86400) + "d ago"; }
  function fmtTs(iso) { var d = parseTs(iso); return d ? d.toISOString().slice(0, 19).replace("T", " ") + " UTC" : "—"; }
  function fmtClock(iso) { var d = parseTs(iso); return d ? d.toISOString().slice(5, 19).replace("T", " ") : "—"; }
  function dur(ms) { if (ms == null || !isFinite(ms)) return "—"; var neg = ms < 0; ms = Math.abs(ms); return (neg ? "-" : "") + Math.floor(ms / 86400000) + "d " + Math.floor((ms % 86400000) / 3600000) + "h"; }
  function badge(text, kind) { return el("span", { class: "badge " + (kind || "gray") }, String(text == null ? "—" : text)); }
  function statusKind(s) {
    s = String(s || "").toLowerCase();
    if (/(approve|trade|entry|open|pass|running|healthy|ok|filled|buy|long|active)/.test(s)) return "green";
    if (/(veto|reject|fail|error|halt|violation|loss|down)/.test(s)) return "red";
    if (/(hold|pending|insufficient|warn|paused|skip|stale|degraded|unknown)/.test(s)) return "amber";
    if (/(exit|close|sell|short)/.test(s)) return "blue";
    return "gray";
  }

  // ---------------------------------------------------------------- states
  function skeleton(n) { var r = []; for (var i = 0; i < (n || 4); i++) r.push(el("div", { class: "skel " + (i % 3 === 0 ? "w1" : i % 3 === 1 ? "w2" : "w3") })); return el("div", { class: "skel-list" }, r); }
  function emptyState(kind, title, desc) {
    var ic = kind === "amber" ? "◔" : kind === "red" ? "△" : "○";
    return el("div", { class: "empty " + (kind || "") }, [el("div", { class: "ic" }, ic), el("div", { class: "t" }, title), desc ? el("div", { class: "d" }, desc) : null]);
  }
  function bind(key, render, empty) {
    var c = cache[key];
    if (!c) return skeleton(4);
    if (!c.ok) return emptyState("red", "Unavailable", "This data source is temporarily unavailable — it will retry automatically.");
    var d = c.data;
    if (d == null || (Array.isArray(d) && d.length === 0)) { empty = empty || {}; return emptyState(empty.kind || "", empty.title || "No data yet", empty.desc); }
    return render(d);
  }

  // ---------------------------------------------------------------- primitives
  function panel(title, opts) {
    opts = opts || {};
    var head = el("div", { class: "phead" }, [el("h2", null, title)]);
    if (opts.tag) head.appendChild(el("span", { class: "tag" }, opts.tag));
    head.appendChild(el("span", { class: "spacer" }));
    if (opts.srcKey) head.appendChild(el("span", { class: "age", "data-age-src": opts.srcKey }, "—"));
    var body = el("div", { class: opts.flush ? "pbody flush" : "pbody" });
    return { node: el("div", { class: "panel" + (opts.cls ? " " + opts.cls : "") }, [head, body]), body: body };
  }
  function table(cols, rows) {
    var thead = el("tr", null, cols.map(function (c) { return el("th", { class: c.num ? "num" : "" }, c.label); }));
    var body = rows.map(function (r) {
      return el("tr", null, cols.map(function (c) {
        var v = c.get(r), td = el("td", { class: c.num ? "num" : "" });
        if (v == null) td.appendChild(na()); else if (typeof v === "object") td.appendChild(v); else td.textContent = String(v);
        return td;
      }));
    });
    return el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, [el("thead", null, thead), el("tbody", null, body)]));
  }
  function kvList(pairs) {
    var out = [];
    pairs.forEach(function (p) {
      out.push(el("div", { class: "k" }, p[0]));
      var vc = el("div", { class: "v" });
      if (p[1] == null) vc.appendChild(na()); else if (typeof p[1] === "object") vc.appendChild(p[1]); else vc.textContent = String(p[1]);
      out.push(vc);
    });
    return el("div", { class: "kv-list" }, out);
  }
  function kpi(label, value, secondary, cls) {
    var v = el("div", { class: "v" });
    if (value == null) { v.appendChild(el("span", { class: "na" }, "No data yet")); }
    else if (typeof value === "object") v.appendChild(value); else v.textContent = String(value);
    var kids = [el("div", { class: "k" }, label), v];
    if (secondary != null) kids.push(el("div", { class: "s" }, secondary));
    return el("div", { class: "kpi" + (cls ? " " + cls : "") }, kids);
  }
  function csStat(k, v) { var vc = el("div", { class: "v" }); if (v == null) vc.appendChild(na()); else if (typeof v === "object") vc.appendChild(v); else vc.textContent = String(v); return el("div", { class: "cs" }, [el("div", { class: "k" }, k), vc]); }
  function gauge(label, frac) {
    var f = pf(frac); var w = f == null ? 0 : Math.max(0, Math.min(1, f)) * 100;
    return el("div", { class: "gauge" }, [
      el("div", { class: "lab" }, [el("span", null, label), el("b", null, f == null ? "N/A" : (f * 100).toFixed(1) + "%")]),
      el("div", { class: "track" }, el("i", { style: "width:" + w + "%" })),
    ]);
  }

  // ---------------------------------------------------------------- hero math
  function heroStats() {
    var run = state.run;
    var uni = cache.universe && cache.universe.ok ? cache.universe.data : null;
    var val = cache.validation && cache.validation.ok ? cache.validation.data : null;
    var t0 = uni ? parseTs(uni.t0) : null;
    var win = (val && val.validation_days != null) ? val.validation_days : null;
    var elapsed = t0 ? Date.now() - t0.getTime() : null;
    var elapsedDays = elapsed != null ? elapsed / 86400000 : null;
    var dayX = elapsedDays != null ? Math.max(1, Math.min(Math.floor(elapsedDays) + 1, win || 99999)) : null;
    var progress = (elapsedDays != null && win) ? Math.max(0, Math.min(1, elapsedDays / win)) : null;
    var endMs = (t0 && win) ? t0.getTime() + win * 86400000 : null;
    return {
      run: run, uni: uni, t0: t0, win: win, elapsed: elapsed, dayX: dayX, progress: progress,
      endMs: endMs, remain: endMs != null ? endMs - Date.now() : null,
      count: uni ? uni.count : null, hash: uni ? uni.selection_hash : null,
      status: run ? String(run.status || "").toUpperCase() : (cache.runs && cache.runs.ok ? "NO RUN" : "—"),
      running: !!(run && run.status === "running"),
    };
  }
  function fact(k, v) { var vc = el("div", { class: "v" }); if (v == null) vc.appendChild(na()); else if (typeof v === "object") vc.appendChild(v); else vc.textContent = String(v); return el("div", { class: "fact" }, [el("div", { class: "k" }, k), vc]); }

  function heroNode() {
    var s = heroStats();
    var p = panel("P9 Paper Validation", { cls: "hero", tag: s.running ? "live" : null, srcKey: "universe" });
    var b = p.body;
    b.appendChild(el("div", { class: "hero-top" }, [
      el("span", { class: "sdot " + statusKind(s.run ? s.run.status : "") + (s.running ? " live" : "") }),
      el("span", { class: "state " + (s.running ? "t-green" : "t-amber") }, s.status),
      el("div", { class: "daychip" }, [
        el("div", { class: "big" }, s.dayX != null ? "Day " + s.dayX + " / " + (s.win || "—") : "—"),
        el("div", { class: "pctline" }, s.progress != null ? (s.progress * 100).toFixed(1) + "% complete" : "progress pending"),
      ]),
    ]));
    b.appendChild(el("div", { class: "hero-progress" }, el("div", { class: "bar" }, el("i", { style: "width:" + (s.progress != null ? (s.progress * 100).toFixed(2) : 0) + "%" }))));
    b.appendChild(el("div", { class: "hero-facts" }, [
      fact("T0", s.t0 ? fmtTs(s.uni.t0) : null),
      fact("Expected end", s.endMs != null ? fmtTs(new Date(s.endMs).toISOString()) : null),
      fact("Elapsed", s.elapsed != null ? dur(s.elapsed) : null),
      fact("Remaining", s.remain != null ? dur(s.remain) : null),
      fact("Frozen universe", s.count != null ? s.count + " symbols" : null),
      fact("Selection hash", s.hash ? el("span", { class: "mono", title: s.hash }, shortId(s.hash)) : null),
      fact("Run", s.run ? el("span", { class: "mono", title: s.run.run_id }, shortId(s.run.run_id)) : null),
      fact("Prereg digest", s.run && s.run.prereg_digest ? el("span", { class: "mono", title: s.run.prereg_digest }, shortId(s.run.prereg_digest)) : null),
    ]));
    return p.node;
  }

  // ---------------------------------------------------------------- KPI rows
  function kpiRow1() {
    var pfd = cache.portfolio && cache.portfolio.ok ? cache.portfolio.data : null;
    var m = cache.metrics && cache.metrics.ok ? cache.metrics.data.metrics : null;
    var run = state.run;
    var eq = pfd ? pfd.equity : null, start = run ? run.starting_equity : null;
    var pnl = (pf(eq) != null && pf(start) != null) ? pf(eq) - pf(start) : null;
    var ret = m ? m.total_return : (pf(eq) != null && pf(start) && pf(start) !== 0 ? pf(eq) / pf(start) - 1 : null);
    var maxdd = m ? m.max_drawdown : (pfd ? pfd.drawdown_pct : null);
    return el("div", { class: "kpis" }, [
      kpi("Paper Equity", eq == null ? null : el("span", null, [money(eq), el("span", { class: "u" }, "USDT")]), start != null ? "Starting: " + money(start) : "Awaiting first snapshot"),
      kpi("P&L", pnl == null ? null : el("span", { class: pnl >= 0 ? "t-green" : "t-red" }, (pnl >= 0 ? "+" : "") + money(pnl)), "since T0", pnl == null ? "" : (pnl >= 0 ? "pos" : "neg")),
      kpi("Return", ret == null ? null : el("span", { class: pf(ret) >= 0 ? "t-green" : "t-red" }, (pf(ret) >= 0 ? "+" : "") + pct(ret)), "net, fee-inclusive", ret == null ? "" : (pf(ret) >= 0 ? "pos" : "neg")),
      kpi("Max Drawdown", maxdd == null ? null : el("span", { class: "t-red" }, pct(maxdd)), "from high-water mark", maxdd == null ? "" : "neg"),
    ]);
  }
  function kpiRow2() {
    var pfd = cache.portfolio && cache.portfolio.ok ? cache.portfolio.data : null;
    var m = cache.metrics && cache.metrics.ok ? cache.metrics.data.metrics : null;
    var pos = cache.positions && cache.positions.ok ? cache.positions.data : null;
    return el("div", { class: "kpis" }, [
      kpi("Open Positions", pos == null ? null : String(pos.length), "live"),
      kpi("Total Trades", m == null ? null : String(m.trade_count), "closed"),
      kpi("Exposure", pfd == null ? null : el("span", null, [money(pfd.total_exposure), el("span", { class: "u" }, "USDT")]), "gross notional"),
      kpi("Win Rate", (m && m.win_rate != null) ? pct(m.win_rate) : null, (m && m.win_rate == null) ? "no closed trades yet" : "closed trades"),
    ]);
  }

  // ---------------------------------------------------------------- equity
  function equityPanel() {
    var p = panel("Equity Curve", { srcKey: "equity", tag: "boundary index" });
    var c = cache.equity;
    var series = (c && c.ok && Array.isArray(c.data)) ? c.data.map(function (x) { return pf(x.equity); }).filter(function (v) { return v != null; }) : [];
    var start = state.run ? pf(state.run.starting_equity) : null;
    var cur = series.length ? series[series.length - 1] : null;
    var delta = (cur != null && start != null) ? cur - start : null;
    p.body.appendChild(el("div", { class: "chart-stat" }, [
      csStat("Current", cur != null ? money(cur) : null),
      csStat("Start", start != null ? money(start) : null),
      csStat("Δ", delta == null ? null : el("span", { class: delta >= 0 ? "t-green" : "t-red" }, (delta >= 0 ? "+" : "") + money(delta))),
      csStat("Points", String(series.length)),
    ]));
    p.body.appendChild(el("div", { class: "chart-wrap" }, el("canvas", { "data-chart": "equity" })));
    p.body.appendChild(el("div", { class: "chart-cap" }, "x-axis = validation boundary index — backend equity points are bucket-ordered (no timestamps)"));
    return p.node;
  }

  // ---------------------------------------------------------------- tables/panels
  function positionsPanel() {
    var p = panel("Open Positions", { srcKey: "positions", flush: true });
    p.body.appendChild(bind("positions", function (rows) {
      return table([
        { label: "Symbol", get: function (r) { return el("b", { class: "mono" }, r.symbol); } },
        { label: "Side", get: function (r) { return badge(r.direction, statusKind(r.direction)); } },
        { label: "Qty", num: true, get: function (r) { return r.quantity; } },
        { label: "Entry", num: true, get: function (r) { return money(r.average_entry); } },
        { label: "Current", num: true, get: function () { return null; } },
        { label: "Value", num: true, get: function () { return null; } },
        { label: "uPnL", num: true, get: function () { return null; } },
        { label: "Stop", num: true, get: function (r) { return money(r.stop_price); } },
        { label: "Target", num: true, get: function (r) { return money(r.target_price); } },
        { label: "Opened", get: function (r) { return fmtClock(r.opened_at); } },
      ], rows);
    }, { title: "No open positions", desc: "No paper positions are currently open." }));
    return p.node;
  }
  function decisionsPanel(tag) {
    var p = panel("Recent Decisions", { srcKey: "decisions", tag: tag, flush: true });
    p.body.appendChild(bind("decisions", function (rows) {
      return table([
        { label: "Time", get: function (r) { return fmtClock(r.decision_time); } },
        { label: "Symbol", get: function (r) { return el("b", { class: "mono" }, r.symbol); } },
        { label: "Outcome", get: function (r) { return badge(r.outcome, statusKind(r.outcome)); } },
        { label: "Stage", get: function (r) { return r.stage; } },
        { label: "Regime", get: function (r) { return r.regime; } },
        { label: "Equity after", num: true, get: function (r) { return money(r.equity_after); } },
        { label: "Exposure", num: true, get: function (r) { return pct(r.exposure_after_pct); } },
        { label: "Reason", get: function (r) { return r.reason; } },
      ], rows);
    }, { title: "No decisions yet", desc: "The validation engine has not recorded a decision at this stage." }));
    return p.node;
  }
  function claudeCard(rows) {
    var top = rows[0];
    return el("div", { class: "aicard" }, [
      el("div", { class: "row" }, [
        el("span", { class: "sym" }, top.symbol || "—"),
        top.action ? badge(top.action, statusKind(top.action)) : null,
        top.decision ? badge(top.decision, statusKind(top.decision)) : null,
        top.failure ? badge(top.failure, "red") : null,
        el("span", { class: "model" }, top.model_id || top.model_class || "—"),
      ]),
      el("div", { class: "when" }, "Latest verdict · " + fmtTs(top.decision_time)),
    ]);
  }
  function claudeIntro() {
    return el("div", { class: "ai-note" }, [el("b", null, "CLAUDE"), el("span", null, "Advisory / veto only — the deterministic RiskManager remains the final authority. This panel reads persisted verdicts; it never calls Claude.")]);
  }
  function claudePanelCompact() {
    var p = panel("Claude", { srcKey: "claude", tag: "advisory" });
    p.body.appendChild(claudeIntro());
    p.body.appendChild(bind("claude", function (rows) { return claudeCard(rows); },
      { title: "No Claude decisions yet", desc: "No advisory verdicts have been persisted for this run." }));
    return p.node;
  }
  function claudePanelFull() {
    var p = panel("Claude Intelligence", { srcKey: "claude", tag: "advisory / veto only" });
    p.body.appendChild(claudeIntro());
    p.body.appendChild(bind("claude", function (rows) {
      var out = el("div", null, [claudeCard(rows)]);
      out.appendChild(table([
        { label: "Time", get: function (r) { return fmtClock(r.decision_time); } },
        { label: "Symbol", get: function (r) { return r.symbol; } },
        { label: "Action", get: function (r) { return r.action ? badge(r.action, statusKind(r.action)) : null; } },
        { label: "Decision", get: function (r) { return r.decision ? badge(r.decision, statusKind(r.decision)) : null; } },
        { label: "Failure", get: function (r) { return r.failure ? el("span", { class: "t-red" }, r.failure) : el("span", { class: "t-muted" }, "—"); } },
        { label: "Model", get: function (r) { return el("span", { class: "mono t-purple" }, r.model_id || r.model_class || "—"); } },
      ], rows));
      return out;
    }, { title: "No Claude decisions yet", desc: "No advisory verdicts have been persisted for this run." }));
    return p.node;
  }
  function riskCards(rows) {
    var top = rows[0];
    return el("div", { class: "kpis", style: "grid-template-columns:repeat(2,1fr)" }, [
      kpi("Latest Decision", badge(top.decision, statusKind(top.decision))),
      kpi("Exposure After", top.exposure_after_pct == null ? null : pct(top.exposure_after_pct), "portfolio"),
      kpi("Risk / Trade", top.recomputed_risk_pct == null ? null : pct(top.recomputed_risk_pct), "recomputed"),
      kpi("Decisions", String(rows.length), "recent window"),
    ]);
  }
  function riskPanelCompact() {
    var p = panel("Risk Snapshot", { srcKey: "risk" });
    p.body.appendChild(bind("risk", function (rows) { return riskCards(rows); },
      { title: "No risk decisions yet", desc: "The RiskManager has not recorded a decision at this stage." }));
    return p.node;
  }
  function riskPanelFull() {
    var p = panel("Risk Monitor", { srcKey: "risk" });
    p.body.appendChild(bind("risk", function (rows) {
      var out = el("div", null, [riskCards(rows), el("div", { style: "height:12px" })]);
      out.appendChild(table([
        { label: "Time", get: function (r) { return fmtClock(r.decision_time); } },
        { label: "Symbol", get: function (r) { return r.symbol; } },
        { label: "Decision", get: function (r) { return badge(r.decision, statusKind(r.decision)); } },
        { label: "Risk %", num: true, get: function (r) { return r.recomputed_risk_pct == null ? null : pct(r.recomputed_risk_pct); } },
        { label: "Exposure after", num: true, get: function (r) { return r.exposure_after_pct == null ? null : pct(r.exposure_after_pct); } },
        { label: "Reason", get: function (r) { return r.reason; } },
      ], rows));
      return out;
    }, { title: "No risk decisions yet", desc: "The RiskManager has not recorded a decision at this stage." }));
    return p.node;
  }
  function newsFeed(rows, n) {
    return table([
      { label: "Available", get: function (r) { return fmtClock(r.available_at); } },
      { label: "Source", get: function (r) { return r.source; } },
      { label: "Headline", get: function (r) { return el("span", null, r.title); } },
      { label: "Trust", num: true, get: function (r) { return r.trust; } },
      { label: "Published", get: function (r) { return fmtClock(r.published_at); } },
    ], n ? rows.slice(0, n) : rows);
  }
  function newsPanelCompact() {
    var p = panel("News Activity", { srcKey: "news", tag: "persisted", flush: true });
    p.body.appendChild(bind("news", function (rows) { return newsFeed(rows, 8); },
      { title: "No news yet", desc: "No decision-time news has been persisted for this run." }));
    return p.node;
  }
  function newsPanelFull() {
    var p = panel("News Activity", { srcKey: "news", tag: "persisted decision-time", flush: true });
    p.body.appendChild(bind("news", function (rows) { return newsFeed(rows); },
      { title: "No news yet", desc: "No decision-time news has been persisted for this run." }));
    return p.node;
  }

  // ---------------------------------------------------------------- health tiles
  function tile(label, statusText, kind, sub) {
    return el("div", { class: "tile" }, [
      el("div", { class: "top" }, [el("span", { class: "sdot " + kind }), el("span", { class: "k" }, label)]),
      el("div", { class: "v" }, statusText),
      sub ? el("div", { class: "sub" }, sub) : null,
    ]);
  }
  function healthTiles(d) {
    var run = state.run;
    var running = run && run.status === "running";
    var ks = d.kill_switch || {};
    var hb = parseTs(d.heartbeat_at);
    return el("div", { class: "tiles" }, [
      tile("Runner", running ? "HEALTHY" : String(d.status || "—").toUpperCase(), running ? "green" : "amber", "status: " + (d.status || "—")),
      tile("Heartbeat", hb ? agoMs(hb.getTime()) : "UNKNOWN", running ? "green" : "amber", hb ? fmtTs(d.heartbeat_at) : "no heartbeat"),
      tile("Database", "HEALTHY", "green", "run DB reachable (read-only)"),
      tile("Kill Switch", String(ks.status || "running").toUpperCase(), statusKind(ks.status || "running"), ks.reason || "no trip"),
      tile("Market Data", "UNKNOWN", "amber", "not individually reported"),
      tile("News / Claude", "UNKNOWN", "amber", "not individually reported"),
    ]);
  }
  function healthPanel(tag) {
    var p = panel("System Health", { srcKey: "health", tag: tag });
    p.body.appendChild(bind("health", function (d) {
      var out = el("div", null, [healthTiles(d), el("div", { style: "height:12px" })]);
      out.appendChild(kvList([
        ["Decisions processed", d.decision_count == null ? null : String(d.decision_count)],
        ["Last decision", d.last_decision_time ? fmtTs(d.last_decision_time) : null],
        ["Kill reason", (d.kill_switch && d.kill_switch.reason) || el("span", { class: "t-muted" }, "—")],
      ]));
      out.appendChild(el("div", { class: "t-muted", style: "margin-top:10px;font-size:10px" },
        "Market Data / News / Claude are not individually reported by the backend; overall liveness is the runner status + heartbeat above."));
      return out;
    }));
    return p.node;
  }

  // ---------------------------------------------------------------- pages
  function renderOverview(node) {
    var m = el("div", { class: "mosaic" });
    m.appendChild(el("div", { class: "m-12" }, heroNode()));
    m.appendChild(el("div", { class: "m-12" }, kpiRow1()));
    m.appendChild(el("div", { class: "m-12" }, kpiRow2()));
    m.appendChild(el("div", { class: "m-8" }, equityPanel()));
    m.appendChild(el("div", { class: "m-4" }, healthPanel("live")));
    m.appendChild(el("div", { class: "m-4" }, riskPanelCompact()));
    m.appendChild(el("div", { class: "m-4" }, claudePanelCompact()));
    m.appendChild(el("div", { class: "m-4" }, newsPanelCompact()));
    m.appendChild(el("div", { class: "m-12" }, decisionsPanel("last 60")));
    m.appendChild(el("div", { class: "m-12" }, positionsPanel()));
    node.appendChild(m);
  }
  function renderPortfolio(node) {
    node.appendChild(kpiRow1());
    node.appendChild(el("div", { style: "height:13px" }));
    var p = panel("Portfolio Snapshot", { srcKey: "portfolio" });
    p.body.appendChild(bind("portfolio", function (d) {
      return kvList([
        ["Equity", money(d.equity)], ["Cash", money(d.cash)], ["Total exposure", money(d.total_exposure)],
        ["Realized P&L (cum)", money(d.realized_pnl_cum)], ["Unrealized P&L", money(d.unrealized_pnl)],
        ["Fees paid (cum)", money(d.fees_paid_cum)], ["High-water mark", money(d.hwm_equity)],
        ["Drawdown", d.drawdown_pct == null ? null : el("span", { class: "t-red" }, pct(d.drawdown_pct))],
        ["Snapshot", fmtTs(d.snapshot_time)],
      ]);
    }, { title: "No portfolio snapshot yet", desc: "Awaiting the first consolidated portfolio snapshot." }));
    node.appendChild(p.node);
  }
  function renderPositions(node) { node.appendChild(kpiRow2()); node.appendChild(el("div", { style: "height:13px" })); node.appendChild(positionsPanel()); }
  function renderDecisions(node) { node.appendChild(decisionsPanel("last 60")); }
  function renderClaude(node) { node.appendChild(claudePanelFull()); }
  function renderNews(node) { node.appendChild(newsPanelFull()); }
  function renderRisk(node) { node.appendChild(riskPanelFull()); }
  function renderSystem(node) { node.appendChild(healthPanel(null)); }

  function renderPerformance(node) {
    node.appendChild(equityPanel());
    node.appendChild(el("div", { style: "height:13px" }));
    var p = panel("Performance Metrics", { srcKey: "metrics", tag: "authoritative" });
    p.body.appendChild(bind("metrics", function (d) {
      var m = d.metrics, du = d.duration || {};
      return el("div", { class: "grid cols-2" }, [
        kvList([
          ["Trades", m.trade_count], ["Win rate", m.win_rate == null ? null : pct(m.win_rate)],
          ["Net expectancy", m.net_expectancy == null ? null : money(m.net_expectancy)],
          ["Profit factor", m.profit_factor == null ? null : m.profit_factor.toFixed(3)],
          ["Total return", m.total_return == null ? null : pct(m.total_return)],
          ["Net P&L", money(m.net_pnl)], ["Gross P&L", money(m.gross_pnl)],
          ["Max drawdown", m.max_drawdown == null ? null : pct(m.max_drawdown)],
          ["Sharpe", m.sharpe == null ? null : m.sharpe.toFixed(2)],
          ["Sortino", m.sortino == null ? null : m.sortino.toFixed(2)],
          ["Calmar", m.calmar == null ? null : m.calmar.toFixed(2)],
        ]),
        el("div", null, [
          kvList([
            ["Calendar days", du.calendar_days == null ? null : du.calendar_days.toFixed(2)],
            ["Boundaries processed", du.processed_boundaries], ["Expected boundaries", du.expected_boundaries],
            ["Gaps", du.gap_boundaries], ["Unusable", du.unusable_boundaries],
          ]),
          el("div", { style: "height:10px" }),
          gauge("Uptime", du.uptime_fraction), gauge("Data quality", du.data_quality_fraction),
        ]),
      ]);
    }, { title: "No metrics yet", desc: "Metrics appear once the run has produced closed trades." }));
    node.appendChild(p.node);
  }

  var GATE_GROUPS = [
    { label: "Operational", re: /(day|uptime|trade|gap|meaningful|operational|duration)/ },
    { label: "Robustness", re: /(bootstrap|autocorr|outlier|monte|carlo|drawdown_ceiling|robust)/ },
    { label: "Diversification", re: /(regime|concentration|top_k|rolling|expectancy|diversif)/ },
    { label: "Other", re: /.*/ },
  ];
  function renderValidation(node) {
    var p = panel("Validation Gates", { srcKey: "validation", tag: "pre-registered" });
    p.body.appendChild(bind("validation", function (d) {
      if (!d.available) return emptyState("amber", "Validation Pending", d.reason || "Not enough data has accumulated to evaluate the pre-registered gates yet.");
      var gates = d.gates || [];
      var counts = { pass: 0, fail: 0, insufficient_data: 0 };
      gates.forEach(function (g) { counts[g.status] = (counts[g.status] || 0) + 1; });
      var head = el("div", { style: "display:flex;gap:8px;align-items:center;margin-bottom:14px;flex-wrap:wrap" }, [
        badge(counts.pass + " pass", "green"), badge(counts.insufficient_data + " insufficient", "amber"), badge(counts.fail + " fail", "red"),
        el("span", { class: "eval-note" }, "BACKEND EVALUATION · this roll-up reflects backend gate statuses only — no verdict is computed in the frontend"),
      ]);
      var groupsWrap = el("div", null, []);
      var used = {};
      GATE_GROUPS.forEach(function (grp) {
        var items = gates.filter(function (g) { return !used[g.name] && grp.re.test(g.name); });
        items.forEach(function (g) { used[g.name] = true; });
        if (!items.length) return;
        groupsWrap.appendChild(el("div", { class: "gate-group" }, [
          el("h3", null, grp.label),
          el("div", { class: "gates" }, items.map(function (g) {
            return el("div", { class: "gate" }, [
              badge(g.status.replace(/_/g, " "), statusKind(g.status)),
              el("span", { class: "nm" }, g.name.replace(/_/g, " ")),
              el("span", { class: "dt", title: g.detail }, g.detail),
            ]);
          })),
        ]));
      });
      var evidence = kvList([
        ["Bootstrap positive", d.bootstrap_positive == null ? null : String(d.bootstrap_positive)],
        ["Autocorrelation", d.autocorrelation == null ? null : pf(d.autocorrelation).toFixed(4)],
        ["Outlier still positive", d.outlier_still_positive == null ? null : String(d.outlier_still_positive)],
        ["Monte-Carlo DD p95", d.monte_carlo_dd_p95 == null ? null : pct(d.monte_carlo_dd_p95)],
        ["Regime cells", d.regime_coverage ? Object.keys(d.regime_coverage).length + " cells" : null],
        ["Validation window", d.validation_days == null ? null : d.validation_days + " days"],
        ["Prereg digest", d.prereg_digest ? el("span", { class: "mono", title: d.prereg_digest }, shortId(d.prereg_digest)) : null],
      ]);
      return el("div", null, [head, groupsWrap, el("div", { style: "height:8px" }),
        el("div", { class: "panel", style: "background:var(--panel-2)" }, [el("div", { class: "phead" }, el("h2", null, "Evidence")), el("div", { class: "pbody" }, evidence)])]);
    }));
    node.appendChild(p.node);
  }

  function renderUniverse(node) {
    var uni = cache.universe;
    var head = panel("Frozen T0 Universe", { srcKey: "universe" });
    if (uni && uni.ok && uni.data) {
      var d = uni.data;
      head.body.appendChild(el("div", { class: "kpis", style: "grid-template-columns:repeat(3,1fr)" }, [
        kpi("Symbols", String(d.count), "frozen at T0"),
        kpi("Selection Hash", d.selection_hash ? el("span", { class: "mono", title: d.selection_hash, style: "font-size:13px" }, shortId(d.selection_hash)) : null, "deterministic"),
        kpi("T0", el("span", { style: "font-size:13px" }, fmtTs(d.t0)), "selected at"),
      ]));
    } else { head.body.appendChild(bind("universe", function () { return null; }, { title: "No frozen universe", desc: "No frozen T0 universe is persisted for this run." })); }
    node.appendChild(head.node);
    node.appendChild(el("div", { style: "height:13px" }));

    var posSet = {};
    if (cache.positions && cache.positions.ok) (cache.positions.data || []).forEach(function (r) { posSet[r.symbol] = true; });
    var tp = panel("Universe Constituents", { srcKey: "universe", tag: "29-symbol frozen set", flush: true });
    tp.body.appendChild(bind("universe", function (d) {
      return table([
        { label: "Rank", num: true, get: function (r) { return r.rank; } },
        { label: "Symbol", get: function (r) { return el("b", { class: "mono" }, r.symbol); } },
        { label: "24h Quote Vol", num: true, get: function (r) { return money(r.quote_volume_24h); } },
        { label: "Position", get: function (r) { return posSet[r.symbol] ? badge("open", "green") : el("span", { class: "t-muted" }, "—"); } },
        { label: "Status", get: function (r) { return badge("frozen", "blue"); } },
        { label: "Selected at", get: function (r) { return fmtClock(r.selected_at); } },
      ], d.symbols || []);
    }, { title: "No frozen universe", desc: "No frozen T0 universe is persisted for this run." }));
    node.appendChild(tp.node);
  }

  function mainDbTable(node, title, srcKey, cols) {
    var p = panel(title, { srcKey: srcKey, tag: "main DB", flush: true });
    p.body.appendChild(bind(srcKey, function (rows) { return table(cols, rows); },
      { title: "No data for this run", desc: "This is a main-database view; it is empty under P9 per-run isolation." }));
    node.appendChild(p.node);
  }
  function renderEvents(node) {
    mainDbTable(node, "System Events", "events", [
      { label: "Time", get: function (r) { return fmtClock(r.created_at); } },
      { label: "Level", get: function (r) { return badge(r.level, statusKind(r.level)); } },
      { label: "Component", get: function (r) { return r.component; } },
      { label: "Message", get: function (r) { return r.message; } },
    ]);
  }
  function renderBacktests(node) {
    mainDbTable(node, "Backtest Runs", "backtests", [
      { label: "Run time", get: function (r) { return fmtClock(r.run_time); } },
      { label: "Dataset", get: function (r) { return r.dataset_name; } },
      { label: "Scenario", get: function (r) { return r.cost_scenario; } },
      { label: "Fill rule", get: function (r) { return r.entry_fill_rule; } },
      { label: "Status", get: function (r) { return badge(r.status, statusKind(r.status)); } },
    ]);
  }
  function renderShadow(node) {
    mainDbTable(node, "Shadow Runs", "shadowRuns", [
      { label: "Run time", get: function (r) { return fmtClock(r.run_time); } },
      { label: "Status", get: function (r) { return badge(r.status, statusKind(r.status)); } },
      { label: "Market", get: function (r) { return r.market_data_source; } },
      { label: "News", get: function (r) { return r.news_source; } },
      { label: "AI", get: function (r) { return r.ai_provider; } },
    ]);
    node.appendChild(el("div", { style: "height:13px" }));
    mainDbTable(node, "Shadow Decisions", "shadowDec", [
      { label: "Time", get: function (r) { return fmtClock(r.decision_time); } },
      { label: "Symbol", get: function (r) { return r.symbol; } },
      { label: "Outcome", get: function (r) { return badge(r.outcome, statusKind(r.outcome)); } },
      { label: "Stage", get: function (r) { return r.stage; } },
      { label: "Regime", get: function (r) { return r.regime; } },
    ]);
  }

  var PAGES = [
    { id: "overview", label: "Overview", sources: ["runs", "health", "portfolio", "metrics", "equity", "positions", "decisions", "claude", "risk", "news", "universe", "validation"], render: renderOverview },
    { id: "portfolio", label: "Portfolio", sources: ["portfolio", "metrics"], render: renderPortfolio },
    { id: "positions", label: "Positions", sources: ["positions", "metrics", "portfolio"], render: renderPositions },
    { id: "decisions", label: "Decisions", sources: ["decisions"], render: renderDecisions },
    { id: "claude", label: "Claude", sources: ["claude"], render: renderClaude },
    { id: "news", label: "News", sources: ["news"], render: renderNews },
    { id: "risk", label: "Risk", sources: ["risk"], render: renderRisk },
    { id: "performance", label: "Performance", sources: ["metrics", "equity"], render: renderPerformance },
    { id: "validation", label: "Validation", sources: ["validation"], render: renderValidation },
    { id: "universe", label: "Universe", sources: ["universe", "positions"], render: renderUniverse },
    { id: "backtests", label: "Backtests", sources: ["backtests"], render: renderBacktests },
    { id: "shadow", label: "Shadow", sources: ["shadowRuns", "shadowDec"], render: renderShadow },
    { id: "system", label: "System Health", sources: ["health"], render: renderSystem },
    { id: "events", label: "Events", sources: ["events"], render: renderEvents },
  ];
  var NAV_GROUPS = [
    { label: "Monitor", ids: ["overview", "portfolio", "positions", "decisions"] },
    { label: "Intelligence", ids: ["claude", "news", "risk"] },
    { label: "Analytics", ids: ["performance", "validation", "universe", "backtests", "shadow"] },
    { label: "System", ids: ["system", "events"] },
  ];

  // ---------------------------------------------------------------- fetch + poll
  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (res) {
      if (!res.ok) return { ok: false, error: "HTTP " + res.status };
      return res.json().then(function (d) { return { ok: true, data: d }; });
    }).catch(function () { return { ok: false, error: "network" }; });
  }
  function fetchSource(key) {
    var s = SOURCES[key]; if (!s) return Promise.resolve();
    var url = s.perRun ? (state.runId ? s.url(state.runId) : null) : s.url();
    if (url == null) return Promise.resolve();
    fetchAt[key] = Date.now();
    return getJSON(url).then(function (r) {
      cache[key] = r.ok ? { ok: true, data: r.data, ts: Date.now() } : { ok: false, err: r.error, ts: Date.now() };
      dirty = true;
      if (key === "runs") reconcileRun();
    });
  }
  function reconcileRun() {
    var c = cache.runs;
    if (!c || !c.ok || !Array.isArray(c.data) || c.data.length === 0) { state.runId = null; state.run = null; return; }
    var top = c.data[0];
    if (top.run_id !== state.runId) {
      state.runId = top.run_id;
      ["health", "portfolio", "positions", "decisions", "claude", "news", "risk", "events",
        "orders", "fills", "equity", "metrics", "validation", "universe"].forEach(function (k) { delete cache[k]; delete fetchAt[k]; });
      fetchSource("universe");
    }
    state.run = top; updateHeader();
  }
  function activePage() { var id = (location.hash || "#overview").slice(1); for (var i = 0; i < PAGES.length; i++) if (PAGES[i].id === id) return PAGES[i]; return PAGES[0]; }
  function tick() {
    var page = activePage(); var need = { runs: 1, health: 1, universe: 1, validation: 1 };
    page.sources.forEach(function (s) { need[s] = 1; });
    Object.keys(need).forEach(function (k) {
      var s = SOURCES[k]; if (!s) return;
      if (s.interval <= 0) { if (!cache[k] && (!s.perRun || state.runId)) fetchSource(k); return; }
      if (Date.now() - (fetchAt[k] || 0) >= s.interval) fetchSource(k);
    });
    if (dirty) { render(); dirty = false; }
    updateAges();
  }

  // ---------------------------------------------------------------- render
  function render() {
    var page = activePage(); var host = document.getElementById("view");
    var node = el("div", { class: "page" });
    node.appendChild(el("div", { class: "page-head" }, [el("h1", null, page.label), el("span", { class: "spacer" }), el("span", { class: "hint" }, "read-only · controls disabled")]));
    try { page.render(node); } catch (e) { node.appendChild(emptyState("red", "Render error", String(e && e.message || e))); }
    host.innerHTML = ""; host.appendChild(node);
    mountCharts(); setActiveNav(); updateHeader(); updateAges();
  }
  function mountCharts() {
    if (chartInst) { try { chartInst.destroy(); } catch (e) {} chartInst = null; }
    var cv = document.querySelector('canvas[data-chart="equity"]'); if (!cv || !window.EquityChart) return;
    var base = state.run ? pf(state.run.starting_equity) : null; var series = [];
    var c = cache.equity; if (c && c.ok && Array.isArray(c.data)) series = c.data.map(function (p) { return pf(p.equity); });
    chartInst = window.EquityChart(cv, { baseline: base }); chartInst.update(series, { baseline: base });
  }
  function setStatus(id, cls, text, live) {
    var e = document.getElementById(id); if (!e) return; e.innerHTML = "";
    e.appendChild(el("span", { class: "sdot " + cls + (live ? " live" : "") })); e.appendChild(el("span", null, text));
  }
  function updateHeader() {
    var s = heroStats();
    var cls = s.running ? "green" : (s.run && s.run.status === "stopped" ? "amber" : (s.run ? "red" : "amber"));
    setStatus("hdr-status", cls, s.status, s.running);
    setStatus("side-status", cls, s.running ? "RUNNING" : s.status, s.running);
    var rn = document.getElementById("hdr-run"); rn.textContent = s.run ? shortId(s.run.run_id) : "—"; rn.title = s.run ? s.run.run_id : "";
    document.getElementById("hdr-updated").textContent = cache.health ? agoMs(cache.health.ts) : "—";
    document.getElementById("hdr-day").textContent = s.dayX != null ? (s.dayX + " / " + (s.win || "—")) : "—";
    document.getElementById("hdr-assets").textContent = s.count != null ? String(s.count) : "—";
  }
  function updateAges() {
    var nodes = document.querySelectorAll("[data-age-src]");
    for (var i = 0; i < nodes.length; i++) {
      var elm = nodes[i], k = elm.getAttribute("data-age-src"), c = cache[k];
      if (!c) { elm.textContent = "—"; elm.classList.remove("stale"); continue; }
      var s = (Date.now() - c.ts) / 1000;
      elm.textContent = (c.ok ? "updated " : "error ") + (s < 60 ? Math.floor(s) + "s" : Math.floor(s / 60) + "m") + " ago";
      var iv = (SOURCES[k] && SOURCES[k].interval) || 15000;
      elm.classList.toggle("stale", !c.ok || s > (iv / 1000) * 3);
    }
  }
  function buildNav() {
    var nav = document.getElementById("nav");
    NAV_GROUPS.forEach(function (g) {
      nav.appendChild(el("div", { class: "grp" }, g.label));
      g.ids.forEach(function (id) {
        var page = PAGES.filter(function (p) { return p.id === id; })[0]; if (!page) return;
        nav.appendChild(el("a", { href: "#" + id, "data-page": id }, [el("span", { class: "dot" }), page.label]));
      });
    });
  }
  function setActiveNav() {
    var id = activePage().id, links = document.querySelectorAll("#nav a");
    for (var i = 0; i < links.length; i++) links[i].classList.toggle("active", links[i].getAttribute("data-page") === id);
  }
  function onHash() {
    var sb = document.getElementById("sidebar"); if (sb) sb.classList.remove("open");
    render(); activePage().sources.forEach(function (k) { fetchSource(k); });
  }

  function boot() {
    buildNav();
    window.addEventListener("hashchange", onHash);
    var mb = document.getElementById("menu-btn");
    if (mb) mb.addEventListener("click", function () { document.getElementById("sidebar").classList.toggle("open"); });
    render();
    fetchSource("runs").then(function () { render(); onHash(); });
    setInterval(tick, 1000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
