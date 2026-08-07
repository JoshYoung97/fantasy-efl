"""Generate the mobile projections page from exported data.

    python scripts/export_app_data.py && python scripts/build_app.py

Writes data/app.html, a self-contained page with the projections embedded.
There is no live fetching: a published page cannot reach the odds API, and the
API key must not ship to a browser. Regenerating before each deadline matches
the weekly gameweek cadence anyway.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "app_data.json"
OUTPUT = ROOT / "data" / "app.html"

TEMPLATE = """<title>Fantasy EFL Projections</title>
<style>
  :root {
    --ink: #0C1116;
    --surface: #161E27;
    --raised: #1E2833;
    --line: #263241;
    --text: #E6EBF1;
    --mist: #8A98A8;
    --floodlight: #E9A13B;
    --pitch: #4A8F63;
    --clay: #C2604E;

    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    --ui: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;

    --step-0: 0.9375rem;
    --step-1: 1.125rem;
    --step-2: 1.5rem;
    --step-3: 2.25rem;
  }

  @media (prefers-color-scheme: light) {
    :root {
      --ink: #F2F4F7;
      --surface: #FFFFFF;
      --raised: #FFFFFF;
      --line: #DDE3EA;
      --text: #10161D;
      --mist: #66748A;
      --floodlight: #B87516;
      --pitch: #35704A;
      --clay: #A8452F;
    }
  }
  :root[data-theme="dark"] {
    --ink: #0C1116; --surface: #161E27; --raised: #1E2833; --line: #263241;
    --text: #E6EBF1; --mist: #8A98A8; --floodlight: #E9A13B;
    --pitch: #4A8F63; --clay: #C2604E;
  }
  :root[data-theme="light"] {
    --ink: #F2F4F7; --surface: #FFFFFF; --raised: #FFFFFF; --line: #DDE3EA;
    --text: #10161D; --mist: #66748A; --floodlight: #B87516;
    --pitch: #35704A; --clay: #A8452F;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--ink);
    color: var(--text);
    font-family: var(--ui);
    font-size: var(--step-0);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }

  .wrap {
    max-width: 40rem;
    margin: 0 auto;
    padding: 0 1rem 4rem;
  }

  .label {
    font-size: 0.6875rem;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--mist);
    font-weight: 600;
  }

  header {
    position: sticky;
    top: 0;
    z-index: 10;
    background: color-mix(in srgb, var(--ink) 94%, transparent);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--line);
    padding: 1rem 0 0.875rem;
    margin-bottom: 1.5rem;
  }
  .head-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }
  h1 {
    font-size: var(--step-2);
    font-weight: 700;
    letter-spacing: -0.025em;
    margin: 0.125rem 0 0;
    text-wrap: balance;
  }
  .countdown {
    font-family: var(--mono);
    font-size: var(--step-1);
    font-variant-numeric: tabular-nums;
    color: var(--floodlight);
    font-weight: 600;
    white-space: nowrap;
  }
  .deadline { font-size: 0.75rem; color: var(--mist); margin-top: 0.125rem; }

  section { margin-bottom: 2.25rem; }
  .sec-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--line);
  }
  h2 {
    font-size: var(--step-1);
    font-weight: 700;
    letter-spacing: -0.015em;
    margin: 0;
  }

  .total {
    font-family: var(--mono);
    font-size: var(--step-3);
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    letter-spacing: -0.03em;
    line-height: 1;
    color: var(--floodlight);
  }
  .total-note { font-size: 0.75rem; color: var(--mist); margin-top: 0.25rem; }
  .summary {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 1rem;
    margin-bottom: 1rem;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }

  ul { list-style: none; margin: 0; padding: 0; }
  .rows { display: flex; flex-direction: column; gap: 1px; }

  .row {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.75rem;
    background: var(--surface);
    border-left: 3px solid var(--pitch);
    padding: 0.6875rem 0.875rem;
  }
  .row.unproven { border-left-color: var(--mist); }
  .row.club-row { border-left-color: var(--floodlight); }

  .pos {
    font-family: var(--mono);
    font-size: 0.6875rem;
    font-weight: 700;
    color: var(--mist);
    width: 2.25rem;
    letter-spacing: 0.04em;
  }
  .who { min-width: 0; }
  .name {
    font-weight: 650;
    letter-spacing: -0.01em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta {
    font-family: var(--mono);
    font-size: 0.75rem;
    color: var(--mist);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .nums { text-align: right; }
  .xp {
    font-family: var(--mono);
    font-size: var(--step-1);
    font-variant-numeric: tabular-nums;
    font-weight: 650;
    line-height: 1.1;
  }
  .own {
    font-family: var(--mono);
    font-size: 0.6875rem;
    color: var(--mist);
    font-variant-numeric: tabular-nums;
  }

  .tag {
    display: inline-block;
    font-family: var(--mono);
    font-size: 0.625rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    padding: 0.0625rem 0.3125rem;
    border-radius: 2px;
    margin-left: 0.375rem;
    vertical-align: 0.05em;
  }
  .tag-c { background: var(--floodlight); color: var(--ink); }
  .tag-v { background: var(--line); color: var(--text); }

  .filters {
    display: flex;
    gap: 0.375rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
  .chip {
    font-family: var(--mono);
    font-size: 0.75rem;
    font-weight: 650;
    letter-spacing: 0.04em;
    padding: 0.4375rem 0.75rem;
    min-height: 2.25rem;
    background: var(--surface);
    color: var(--mist);
    border: 1px solid var(--line);
    border-radius: 3px;
    cursor: pointer;
    transition: none;
  }
  @media (prefers-reduced-motion: no-preference) {
    .chip { transition: background-color 0.12s ease, color 0.12s ease; }
  }
  .chip[aria-pressed="true"] {
    background: var(--floodlight);
    color: var(--ink);
    border-color: var(--floodlight);
  }
  .chip:focus-visible,
  a:focus-visible { outline: 2px solid var(--floodlight); outline-offset: 2px; }

  .outlook {
    display: flex;
    gap: 2px;
    margin-top: 0.3125rem;
  }
  .fx {
    font-family: var(--mono);
    font-size: 0.625rem;
    font-weight: 700;
    line-height: 1;
    min-width: 1.125rem;
    padding: 0.1875rem 0;
    text-align: center;
    border-radius: 2px;
    background: var(--raised);
    color: var(--mist);
  }
  .fx.double { background: var(--floodlight); color: var(--ink); }
  .fx.blank { opacity: 0.35; }

  .outlook-key {
    display: flex;
    gap: 2px;
    margin-bottom: 0.5rem;
    padding-left: 0.875rem;
  }
  .outlook-key .fx { background: none; color: var(--mist); font-weight: 600; }

  .more {
    display: block;
    width: 100%;
    margin-top: 1px;
    font-family: var(--mono);
    font-size: 0.75rem;
    font-weight: 650;
    letter-spacing: 0.04em;
    padding: 0.6875rem;
    min-height: 2.75rem;
    background: var(--surface);
    color: var(--floodlight);
    border: none;
    border-left: 3px solid var(--line);
    cursor: pointer;
  }
  .more:focus-visible { outline: 2px solid var(--floodlight); outline-offset: -2px; }

  .mins {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: 0.625rem;
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid var(--line);
  }
  .mins input[type="range"] {
    flex: 1;
    min-width: 0;
    height: 1.75rem;
    accent-color: var(--floodlight);
    cursor: pointer;
  }
  .mins input:focus-visible { outline: 2px solid var(--floodlight); outline-offset: 2px; }
  .mins-val {
    font-family: var(--mono);
    font-size: 0.6875rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--mist);
    min-width: 3.5rem;
    text-align: right;
  }
  .mins-val.set { color: var(--floodlight); }
  .reset {
    font-family: var(--mono);
    font-size: 0.625rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    background: none;
    border: 1px solid var(--line);
    border-radius: 2px;
    color: var(--mist);
    padding: 0.25rem 0.375rem;
    min-height: 1.75rem;
    cursor: pointer;
    visibility: hidden;
  }
  .reset.on { visibility: visible; color: var(--floodlight); border-color: var(--floodlight); }
  .reset:focus-visible { outline: 2px solid var(--floodlight); outline-offset: 1px; }

  .row.adjusted { border-left-color: var(--floodlight); }
  .delta {
    font-family: var(--mono);
    font-size: 0.6875rem;
    font-weight: 650;
    font-variant-numeric: tabular-nums;
  }
  .delta.up { color: var(--pitch); }
  .delta.down { color: var(--clay); }

  .odds-box {
    background: var(--surface);
    border: 1px solid var(--line);
    border-left: 3px solid var(--floodlight);
    border-radius: 4px;
    padding: 0.875rem;
    margin-bottom: 1rem;
  }
  .odds-box select {
    width: 100%;
    font-family: var(--ui);
    font-size: 0.875rem;
    font-weight: 650;
    padding: 0.5rem;
    min-height: 2.5rem;
    margin-bottom: 0.75rem;
    background: var(--raised);
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 3px;
  }
  .odds-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
  }
  .odds-field { display: flex; flex-direction: column; gap: 0.25rem; }
  .odds-field label {
    font-size: 0.625rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--mist);
    font-weight: 650;
  }
  .odds-field input {
    font-family: var(--mono);
    font-size: 0.9375rem;
    font-variant-numeric: tabular-nums;
    font-weight: 650;
    width: 100%;
    padding: 0.4375rem 0.5rem;
    min-height: 2.5rem;
    background: var(--raised);
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 3px;
    text-align: center;
  }
  .odds-field input:focus-visible,
  .odds-box select:focus-visible {
    outline: 2px solid var(--floodlight);
    outline-offset: 1px;
  }
  .odds-out {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
    margin-top: 0.75rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--line);
    flex-wrap: wrap;
  }
  .odds-pts {
    font-family: var(--mono);
    font-size: 1.5rem;
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--floodlight);
    line-height: 1;
  }
  .odds-note {
    font-family: var(--mono);
    font-size: 0.6875rem;
    color: var(--mist);
    text-align: right;
  }
  .odds-warn { color: var(--clay); }

  .warn {
    background: var(--surface);
    border: 1px solid var(--line);
    border-left: 3px solid var(--clay);
    border-radius: 4px;
    padding: 1rem;
  }
  .warn p { margin: 0 0 0.75rem; font-size: 0.875rem; }
  .warn strong { color: var(--clay); }
  .blind {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 0.375rem 0.75rem;
    font-family: var(--mono);
    font-size: 0.8125rem;
    font-variant-numeric: tabular-nums;
    padding-top: 0.75rem;
    border-top: 1px solid var(--line);
  }
  .blind .o { color: var(--clay); font-weight: 650; }

  footer {
    margin-top: 2.5rem;
    padding-top: 1rem;
    border-top: 1px solid var(--line);
    font-size: 0.75rem;
    color: var(--mist);
  }
  footer p { margin: 0 0 0.5rem; }
  .stamp { font-family: var(--mono); }

  @media (max-width: 24rem) {
    .pos { display: none; }
    h1 { font-size: 1.3125rem; }
  }
</style>

<div class="wrap">
  <header>
    <div class="label">Fantasy EFL &middot; projections</div>
    <div class="head-row">
      <h1 id="gw"></h1>
      <div class="countdown" id="countdown" aria-live="polite"></div>
    </div>
    <div class="deadline" id="deadline"></div>
  </header>

  <section>
    <div class="sec-head">
      <h2>Recommended squad</h2>
      <span class="label" id="formation"></span>
    </div>
    <div class="summary">
      <div>
        <div class="total" id="total"></div>
        <div class="total-note" id="totalnote">projected points, captain doubled</div>
      </div>
      <div class="total-note" id="poolnote"></div>
    </div>
    <ul class="rows" id="squad"></ul>
  </section>

  <section>
    <div class="sec-head"><h2>Club picks</h2><span class="label">2 of 72</span></div>
    <ul class="rows" id="clubs"></ul>
  </section>

  <section>
    <div class="sec-head">
      <h2>All clubs</h2><span class="label" id="clubcount"></span>
    </div>
    <div class="odds-box">
      <select id="oddsclub" aria-label="Club to reprice"></select>
      <div class="odds-grid">
        <div class="odds-field">
          <label for="oddswin">Win</label>
          <input id="oddswin" type="number" inputmode="decimal" step="0.01" min="1.01">
        </div>
        <div class="odds-field">
          <label for="oddsover">Over 2.5</label>
          <input id="oddsover" type="number" inputmode="decimal" step="0.01" min="1.01">
        </div>
      </div>
      <div class="odds-out">
        <div>
          <div class="odds-pts" id="oddspts">&ndash;</div>
          <div class="odds-note" style="text-align:left" id="oddsbase"></div>
        </div>
        <div class="odds-note" id="oddsimplied"></div>
      </div>
    </div>

    <div class="outlook-key" id="outlookkey" aria-hidden="true"></div>
    <ul class="rows" id="clubtable"></ul>
    <button class="more" id="moreclubs" type="button"></button>
  </section>

  <section>
    <div class="sec-head"><h2>Player pool</h2><span class="label" id="poolcount"></span></div>
    <div class="filters" id="filters" role="group" aria-label="Filter by position"></div>
    <ul class="rows" id="pool"></ul>
  </section>

  <section>
    <div class="sec-head"><h2>Where this is blind</h2></div>
    <div class="warn">
      <p><strong>About a third of all ownership</strong> sits on players with no
      EFL record, so the model cannot rate them. They are ex-Premier League
      players at relegated clubs. Trust your own judgement on these until they
      have played a few games.</p>
      <div class="blind" id="blind"></div>
    </div>
  </section>

  <footer>
    <p>Projections come from de-vigged betting markets for fixture context and
    last season&rsquo;s Fantasy EFL stats for player rates. Rows with a grey
    edge are projected from position averages rather than a player&rsquo;s own
    record.</p>
    <p>Lockout is rolling: each player locks when their own club kicks off, not
    at a single gameweek deadline. Confirmed line-ups land about an hour
    before kickoff, so team news is usually still actionable.</p>
    <p>Repricing a club takes your decimal odds at face value, so a
    bookmaker&rsquo;s margin is left in and probabilities read a few percent
    high; exchange prices give a truer answer. Win and over 2.5 between them
    fix both goal rates exactly, so the clean sheet price is derived rather
    than asked for &mdash; it is shown back to you as a check. Repricing
    updates the club figure only; player projections need a re-solve.</p>
    <p class="stamp" id="stamp"></p>
  </footer>
</div>

<script>
  const DATA = __DATA__;

  const fmt = (n) => n.toFixed(2);
  const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; };

  const lockLabel = (iso) => iso
    ? new Date(iso).toLocaleString(undefined,
        { weekday: "short", hour: "2-digit", minute: "2-digit" })
    : "";

  function playerRow(p, opts = {}) {
    const li = el("li", "row" + (p.proven ? "" : " unproven"));
    li.append(el("div", "pos", p.pos));

    const who = el("div", "who");
    const name = el("div", "name");
    name.append(document.createTextNode(p.name));
    if (opts.captain) name.append(Object.assign(el("span", "tag tag-c", "C")));
    if (opts.vice) name.append(Object.assign(el("span", "tag tag-v", "V")));
    who.append(name);
    let meta = p.club + "  \\u00b7  " + p.opp + " (" + (p.away ? "A" : "H") + ")";
    // Lock times only in the squad, where they drive a decision. In the pool
    // they would crowd the row for no gain.
    if (opts.showLock && p.kickoff) meta += "  \\u00b7  locks " + lockLabel(p.kickoff);
    who.append(el("div", "meta", meta));
    li.append(who);

    const nums = el("div", "nums");
    nums.append(el("div", "xp", fmt(p.xp)));
    nums.append(el("div", "own", p.own.toFixed(1) + "% owned"));
    li.append(nums);
    return li;
  }

  function clubRow(c) {
    const li = el("li", "row club-row");
    li.append(el("div", "pos", c.away ? "AWAY" : "HOME"));
    const who = el("div", "who");
    who.append(el("div", "name", c.name));
    who.append(el("div", "meta", "v " + c.opp));
    li.append(who);
    const nums = el("div", "nums");
    nums.append(el("div", "xp", fmt(c.xp)));
    li.append(nums);
    return li;
  }

  // Header
  document.getElementById("gw").textContent = DATA.gameweek;
  document.getElementById("formation").textContent = DATA.squad.formation;
  document.getElementById("total").textContent = fmt(DATA.squad.total);
  document.getElementById("poolnote").textContent =
    DATA.stats.pool + " players considered";
  document.getElementById("poolcount").textContent = "top 20 by position";

  // Lockout is rolling -- each player locks at their own kickoff, not at one
  // gameweek deadline. Counting down to the first fixture in the round would
  // cost hours of usable time, and those are the hours when team news lands.
  const squadLocks = DATA.squad.players
    .map((p) => p.kickoff).filter(Boolean).map((k) => new Date(k)).sort((a, b) => a - b);
  const deadline = squadLocks.length ? squadLocks[0] : new Date(DATA.deadline);
  const lastLock = squadLocks.length ? squadLocks[squadLocks.length - 1] : deadline;

  const opts = { weekday: "short", day: "numeric", month: "short",
                 hour: "2-digit", minute: "2-digit" };
  document.getElementById("deadline").textContent =
    deadline.getTime() === lastLock.getTime()
      ? "Squad locks " + deadline.toLocaleString(undefined, opts)
      : "Squad locks " + deadline.toLocaleString(undefined, opts) +
        " to " + lastLock.toLocaleString(undefined,
          { hour: "2-digit", minute: "2-digit" }) + ", player by player";

  function tick() {
    const left = deadline - new Date();
    const node = document.getElementById("countdown");
    if (left <= 0) { node.textContent = "LOCKED"; return; }
    const d = Math.floor(left / 86400000);
    const h = Math.floor(left / 3600000) % 24;
    const m = Math.floor(left / 60000) % 60;
    node.textContent = d > 0 ? d + "d " + String(h).padStart(2, "0") + "h"
                             : String(h).padStart(2, "0") + "h " + String(m).padStart(2, "0") + "m";
  }
  tick();
  setInterval(tick, 30000);

  // Squad, with a minutes control per player.
  //
  // The model estimates minutes from last season's appearance rate, which is
  // its single largest source of error. Confirmed team news beats that
  // estimate outright, so each row can be overridden and the total recomputed.
  // Values come from a curve precomputed in Python rather than a scoring model
  // reimplemented here, so the maths has exactly one home.
  const squadList = document.getElementById("squad");
  const order = { GK: 0, DEF: 1, MID: 2, FWD: 3 };
  const GRID = DATA.minutes_grid || [];
  const overrides = new Map();

  const squadOrder = DATA.squad.players
    .slice()
    .sort((a, b) => order[a.pos] - order[b.pos] || b.xp - a.xp);

  function pointsFor(p) {
    const idx = overrides.get(p.name);
    return idx === undefined ? p.xp : (p.curve[idx] ?? p.xp);
  }

  function recalcTotal() {
    const base = squadOrder.reduce((sum, p) => sum + pointsFor(p), 0);
    const captain = squadOrder.find((p) => p.captain);
    const clubs = DATA.squad.clubs.reduce((s, c) => s + c.xp, 0);
    const total = base + (captain ? pointsFor(captain) : 0) + clubs;

    document.getElementById("total").textContent = fmt(total);
    const shift = total - DATA.squad.total;
    document.getElementById("totalnote").textContent =
      overrides.size === 0
        ? "projected points, captain doubled"
        : (shift >= 0 ? "+" : "") + shift.toFixed(2) + " vs the model's estimate";
  }

  function minutesControl(p, row, valueNode) {
    const wrap = el("div", "mins");

    // The curve is sampled at every minute, so the slider index is simply the
    // number of minutes -- no interpolation, and both discontinuities (the
    // appearance point at 1, the doubled appearance and clean sheet at 60)
    // land exactly where they should.
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = String(GRID.length - 1);
    slider.step = "1";
    // Start at the model's own estimate rather than 90. Early in the season
    // that is well short of a full match, and it sharpens as appearances
    // accumulate -- so the control opens at something defensible instead of
    // asserting everyone plays the whole game.
    const seed = Number.isFinite(p.xmins) ? p.xmins : GRID.length - 1;
    slider.value = String(Math.max(0, Math.min(GRID.length - 1, seed)));
    slider.setAttribute("aria-label", "Expected minutes for " + p.name);

    const readout = el("div", "mins-val",
      Number.isFinite(p.xmins) ? "~" + p.xmins + " mins" : "auto");
    const reset = el("button", "reset", "AUTO");
    reset.type = "button";
    reset.setAttribute("aria-label", "Use the model's estimate for " + p.name);

    function apply(idx) {
      if (idx === undefined) {
        overrides.delete(p.name);
        readout.textContent = Number.isFinite(p.xmins) ? "~" + p.xmins + " mins" : "auto";
        readout.classList.remove("set");
        reset.classList.remove("on");
        row.classList.remove("adjusted");
      } else {
        overrides.set(p.name, idx);
        readout.textContent = GRID[idx] + " mins";
        readout.classList.add("set");
        reset.classList.add("on");
        row.classList.add("adjusted");
      }
      valueNode.textContent = fmt(pointsFor(p));
      recalcTotal();
    }

    slider.addEventListener("input", () => apply(Number(slider.value)));
    reset.addEventListener("click", () => {
      slider.value = String(GRID.length - 1);
      apply(undefined);
    });

    wrap.append(slider, readout, reset);
    return wrap;
  }

  squadOrder.forEach((p) => {
    const row = playerRow(p, { captain: p.captain, vice: p.vice, showLock: true });
    if (GRID.length && p.curve && p.curve.length === GRID.length) {
      row.append(minutesControl(p, row, row.querySelector(".xp")));
    }
    squadList.append(row);
  });
  recalcTotal();

  DATA.squad.clubs.forEach((c) => document.getElementById("clubs").append(clubRow(c)));

  // Full club table, with fixture counts for the coming weeks. Counts only --
  // odds exist for the next round alone, so there is nothing honest to project
  // beyond it.
  const CLUBS_SHOWN = 12;
  const clubTable = document.getElementById("clubtable");
  const moreClubs = document.getElementById("moreclubs");
  let clubsExpanded = false;

  document.getElementById("clubcount").textContent =
    DATA.outlook_weeks.length + "-week fixture count";

  const key = document.getElementById("outlookkey");
  DATA.outlook_weeks.forEach((w) =>
    key.append(el("span", "fx", w.replace("GW ", ""))));

  function outlookStrip(counts) {
    const strip = el("div", "outlook");
    counts.forEach((n) => {
      const cell = el("span", "fx" + (n > 1 ? " double" : n ? "" : " blank"),
                      n ? String(n) : "\\u00b7");
      strip.append(cell);
    });
    return strip;
  }

  function clubTableRow(c, rank) {
    const li = el("li", "row club-row");
    li.append(el("div", "pos", String(rank)));
    const who = el("div", "who");
    who.append(el("div", "name", c.name));
    who.append(el("div", "meta",
      c.opp + " (" + (c.away ? "A" : "H") + ")  \\u00b7  CS " + Math.round(c.cs * 100) + "%"));
    if (c.outlook && c.outlook.length) who.append(outlookStrip(c.outlook));
    li.append(who);
    const nums = el("div", "nums");
    nums.append(el("div", "xp", fmt(c.xp)));
    li.append(nums);
    return li;
  }

  function renderClubs() {
    clubTable.replaceChildren();
    const shown = clubsExpanded ? DATA.clubs : DATA.clubs.slice(0, CLUBS_SHOWN);
    shown.forEach((c, i) => clubTable.append(clubTableRow(c, i + 1)));
    moreClubs.textContent = clubsExpanded
      ? "Show fewer"
      : "Show all " + DATA.clubs.length + " clubs";
    moreClubs.setAttribute("aria-expanded", String(clubsExpanded));
  }

  moreClubs.addEventListener("click", () => {
    clubsExpanded = !clubsExpanded;
    renderClubs();
  });
  renderClubs();

  // Pool with position filter
  const filters = document.getElementById("filters");
  const pool = document.getElementById("pool");
  let active = "MID";

  function renderPool() {
    pool.replaceChildren();
    DATA.positions[active].forEach((p) => pool.append(playerRow(p)));
  }

  ["GK", "DEF", "MID", "FWD"].forEach((pos) => {
    const b = el("button", "chip", pos);
    b.type = "button";
    b.setAttribute("aria-pressed", String(pos === active));
    b.addEventListener("click", () => {
      active = pos;
      filters.querySelectorAll(".chip").forEach((c) =>
        c.setAttribute("aria-pressed", String(c.textContent === pos)));
      renderPool();
    });
    filters.append(b);
  });
  renderPool();

  // ---- Club repricing -------------------------------------------------
  //
  // Club maths ported from goals.py and expected.py, verified against the
  // Python implementation for all 72 fixtures (largest disagreement 6e-9).
  // This is the only scoring logic duplicated outside Python, and it covers
  // clubs alone -- player projections need the floor-function distributions,
  // which stay in one place.
  const MAX_GOALS = 15;

  function poissonPmf(k, rate) {
    if (rate <= 0) return k === 0 ? 1 : 0;
    let logFact = 0;
    for (let i = 2; i <= k; i++) logFact += Math.log(i);
    return Math.exp(-rate + k * Math.log(rate) - logFact);
  }

  function matchProbabilities(homeRate, awayRate) {
    const home = [], away = [];
    for (let i = 0; i <= MAX_GOALS; i++) {
      home.push(poissonPmf(i, homeRate));
      away.push(poissonPmf(i, awayRate));
    }
    let pHome = 0, pDraw = 0, pAway = 0;
    for (let i = 0; i <= MAX_GOALS; i++) {
      for (let j = 0; j <= MAX_GOALS; j++) {
        const joint = home[i] * away[j];
        if (i > j) pHome += joint; else if (i === j) pDraw += joint; else pAway += joint;
      }
    }
    return [pHome, pDraw, pAway];
  }

  const tailFrom = (n, rate) => {
    let below = 0;
    for (let k = 0; k < n; k++) below += poissonPmf(k, rate);
    return 1 - below;
  };

  function clubPoints(scored, conceded, away) {
    const [pHome, pDraw, pAway] =
      matchProbabilities(away ? conceded : scored, away ? scored : conceded);
    const pWin = away ? pAway : pHome;
    let pts = 5 * pWin + 3 * pDraw;
    if (away) pts += 2 * pWin;
    pts += 2 * poissonPmf(0, conceded);
    pts += 2 * tailFrom(2, scored);
    pts += 2 * tailFrom(4, scored);
    return { points: pts, pWin, pDraw, cleanSheet: poissonPmf(0, conceded) };
  }

  const overTwoFive = (scored, conceded) => tailFrom(3, scored + conceded);

  // Three prices over-determine two goal rates, so real markets will not agree
  // exactly. Least squares over a refining grid degrades gracefully when they
  // conflict, rather than privileging whichever pair happened to be solved.
  function fitRates(targets, away) {
    let lo = [0.05, 0.05], hi = [5.0, 5.0], best = [1.3, 1.3];
    for (let pass = 0; pass < 5; pass++) {
      const steps = 24;
      let bestErr = Infinity;
      for (let i = 0; i <= steps; i++) {
        for (let j = 0; j <= steps; j++) {
          const scored = lo[0] + ((hi[0] - lo[0]) * i) / steps;
          const conceded = lo[1] + ((hi[1] - lo[1]) * j) / steps;
          const r = clubPoints(scored, conceded, away);
          let err = 0;
          if (targets.win != null) err += (r.pWin - targets.win) ** 2;
          if (targets.cs != null) err += (r.cleanSheet - targets.cs) ** 2;
          if (targets.over != null) err += (overTwoFive(scored, conceded) - targets.over) ** 2;
          if (err < bestErr) { bestErr = err; best = [scored, conceded]; }
        }
      }
      const sx = (hi[0] - lo[0]) / steps, sy = (hi[1] - lo[1]) / steps;
      lo = [Math.max(0.05, best[0] - sx), Math.max(0.05, best[1] - sy)];
      hi = [best[0] + sx, best[1] + sy];
    }
    return { scored: best[0], conceded: best[1], err: Math.sqrt(0) };
  }

  const select = document.getElementById("oddsclub");
  const winIn = document.getElementById("oddswin");
  const overIn = document.getElementById("oddsover");
  const ptsOut = document.getElementById("oddspts");
  const baseOut = document.getElementById("oddsbase");
  const impliedOut = document.getElementById("oddsimplied");

  const toOdds = (p) => (p > 0 ? (1 / p).toFixed(2) : "");

  DATA.clubs.forEach((c, i) => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = c.name + " v " + c.opp + " (" + (c.away ? "A" : "H") + ")";
    select.append(o);
  });

  function marketRates(c) {
    // Recover the goal rates behind the exported probabilities.
    return fitRates({ win: c.win, cs: c.cs }, c.away);
  }

  function fillFromMarket() {
    const c = DATA.clubs[Number(select.value)];
    const r = marketRates(c);
    winIn.value = toOdds(c.win);
    overIn.value = toOdds(overTwoFive(r.scored, r.conceded));
    recalcOdds();
  }

  function recalcOdds() {
    const c = DATA.clubs[Number(select.value)];
    const read = (input) => {
      const v = parseFloat(input.value);
      return Number.isFinite(v) && v > 1 ? 1 / v : null;
    };
    const targets = { win: read(winIn), over: read(overIn) };

    if (targets.win == null && targets.over == null) {
      ptsOut.textContent = "\\u2013";
      impliedOut.textContent = "enter at least one price";
      return;
    }

    const fit = fitRates(targets, c.away);
    const r = clubPoints(fit.scored, fit.conceded, c.away);
    ptsOut.textContent = r.points.toFixed(2);

    const shift = r.points - c.xp;
    baseOut.textContent = "market says " + c.xp.toFixed(2) +
      "  (" + (shift >= 0 ? "+" : "") + shift.toFixed(2) + ")";

    // Show what the fitted rates imply, so conflicting prices are visible
    // rather than silently averaged away.
    const back = [
      targets.win != null ? "win " + toOdds(r.pWin) : null,
      targets.over != null ? "o2.5 " + toOdds(overTwoFive(fit.scored, fit.conceded)) : null,
      "cs " + toOdds(r.cleanSheet),
    ].filter(Boolean).join("  ");
    impliedOut.textContent =
      fit.scored.toFixed(2) + " scored, " + fit.conceded.toFixed(2) + " conceded\\n" + back;
    impliedOut.style.whiteSpace = "pre-line";
  }

  select.addEventListener("change", fillFromMarket);
  [winIn, overIn].forEach((el) => el.addEventListener("input", recalcOdds));
  fillFromMarket();

  // Blind spots
  const blind = document.getElementById("blind");
  DATA.blindspots.forEach((b) => {
    blind.append(el("div", null, b.name + "  " + b.club));
    blind.append(el("div", "o", b.own.toFixed(1) + "%"));
  });

  document.getElementById("stamp").textContent =
    "Generated " + new Date(DATA.generated).toLocaleString(undefined, {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"
    });
</script>
"""


def main() -> int:
    if not DATA.exists():
        print("no data -- run: python scripts/export_app_data.py", file=sys.stderr)
        return 1

    payload = json.loads(DATA.read_text(encoding="utf-8"))
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    OUTPUT.write_text(html, encoding="utf-8")

    print(f"wrote {OUTPUT}  ({len(html) // 1024} KB)")
    print(f"  {payload['gameweek']}, locks {payload['deadline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
