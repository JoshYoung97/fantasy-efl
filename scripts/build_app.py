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

    /* Fixture difficulty, 1 (most favourable) to 5 (least). Steps through
       the palette's own green and clay rather than a generic traffic light,
       so it reads as part of the page. Text colour flips at tier 3, where
       the ground stops being light enough for dark type. */
    --t1: #4E9E5F;
    --t2: #86A343;
    --t3: #C29A33;
    --t4: #BE6D3C;
    --t5: #9B3A2F;
    --t1-ink: #08120B;
    --t2-ink: #0C1206;
    --t3-ink: #14100A;
    --t4-ink: #FBEFE8;
    --t5-ink: #FCEDEA;

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
      /* Deepened for contrast against a white ground. */
      --t1: #3B8A4C;
      --t2: #6E8B34;
      --t3: #A87F1E;
      --t4: #A85628;
      --t5: #8A2A20;
      --t1-ink: #FFFFFF;
      --t2-ink: #FFFFFF;
      --t3-ink: #FFFFFF;
      --t4-ink: #FFFFFF;
      --t5-ink: #FFFFFF;
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

  .tier {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-family: var(--mono);
    font-size: 0.625rem;
    font-weight: 700;
    min-width: 1.125rem;
    height: 1.125rem;
    border-radius: 2px;
    margin-right: 0.375rem;
    vertical-align: 0.05em;
  }
  .tier-1 { background: var(--t1); color: var(--t1-ink); }
  .tier-2 { background: var(--t2); color: var(--t2-ink); }
  .tier-3 { background: var(--t3); color: var(--t3-ink); }
  .tier-4 { background: var(--t4); color: var(--t4-ink); }
  .tier-5 { background: var(--t5); color: var(--t5-ink); }

  .tier-key {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    font-size: 0.625rem;
    color: var(--mist);
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
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

  .row.unavailable { border-left-color: var(--clay); }
  /* After .unavailable: once a player has been overridden, that takes
     precedence over the model's own "not expected to play" warning. */
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

  .search {
    width: 100%;
    font-family: var(--ui);
    font-size: 0.875rem;
    padding: 0.5rem 0.75rem;
    min-height: 2.5rem;
    margin-bottom: 0.75rem;
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 3px;
  }
  .search:focus-visible { outline: 2px solid var(--floodlight); outline-offset: 1px; }

  .toolrow {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
  .toolrow .search { flex: 1; min-width: 10rem; margin-bottom: 0; }
  .sortselect {
    font-family: var(--ui);
    font-size: 0.8125rem;
    font-weight: 650;
    padding: 0 0.5rem;
    min-height: 2.5rem;
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 3px;
  }
  .sortselect:focus-visible { outline: 2px solid var(--floodlight); outline-offset: 1px; }

  .statstoggle {
    font-family: var(--mono);
    font-size: 0.625rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    background: none;
    border: 1px solid var(--line);
    border-radius: 2px;
    color: var(--mist);
    padding: 0.25rem 0.5rem;
    min-height: 1.75rem;
    cursor: pointer;
    margin-top: 0.375rem;
  }
  .statstoggle.on { color: var(--floodlight); border-color: var(--floodlight); }
  .statstoggle:focus-visible { outline: 2px solid var(--floodlight); outline-offset: 1px; }

  .stats-panel {
    grid-column: 1 / -1;
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid var(--line);
  }
  .stats-panel .odds-grid { grid-template-columns: repeat(2, 1fr); }
  .stats-panel .reset { margin-top: 0.5rem; }

  @media (min-width: 30rem) {
    .stats-panel .odds-grid { grid-template-columns: repeat(3, 1fr); }
  }

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

    <div class="tier-key" id="tierkey"></div>
    <div class="outlook-key" id="outlookkey" aria-hidden="true"></div>
    <ul class="rows" id="clubtable"></ul>
    <button class="more" id="moreclubs" type="button"></button>
  </section>

  <section>
    <div class="sec-head"><h2>Player pool</h2><span class="label" id="poolcount"></span></div>
    <div class="filters" id="filters" role="group" aria-label="Filter by position"></div>
    <div class="toolrow">
      <input class="search" id="poolsearch" type="search" placeholder="Search player or club&hellip;" aria-label="Search the player pool">
      <select class="sortselect" id="poolsort" aria-label="Sort the player pool">
        <option value="xp">Sort: projected points</option>
        <option value="own">Sort: ownership</option>
        <option value="name">Sort: name</option>
      </select>
    </div>
    <ul class="rows" id="pool"></ul>
    <button class="more" id="morepool" type="button"></button>
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
  // Rates arrive as a positional array with a shared key list, because
  // naming every field on every fixture cost 38% of the payload in repeated
  // keys. Expand once here so everything downstream works with named fields.
  (DATA.pool || []).forEach((p) => {
    (p.fixtures || []).forEach((f) => {
      if (!f.r) return;
      DATA.rateKeys.forEach((k, i) => { f[k] = f.r[i]; });
      f.dispersion = DATA.dispersion;
      delete f.r;
    });
  });

  const POOL_BY_ID = new Map(DATA.pool.map((p) => [p.id, p]));

  const fmt = (n) => n.toFixed(2);
  const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; };

  // Fixture difficulty, straight from the market's price for the match.
  function tierChip(tier) {
    const chip = el("span", "tier tier-" + tier, String(tier));
    chip.title = "fixture difficulty " + tier + " of 5";
    return chip;
  }

  const lockLabel = (iso) => iso
    ? new Date(iso).toLocaleString(undefined,
        { weekday: "short", hour: "2-digit", minute: "2-digit" })
    : "";

  // ---- Player scoring, ported from fantasy_efl/expected.py -----------
  //
  // E[floor(X/k)] != E[X]/k for a floor-function rule ("every 4 clearances"),
  // so this is the exact expectation over a negative-binomial pmf --
  // E[floor(X/k)] = sum_{j>=1} P(X >= j*k) -- not the naive mean/k. Verified
  // against expected_player_points() across 2000 randomised cases spanning
  // every position and the 59/60/61-minute boundary; largest disagreement
  // 2e-12, i.e. floating-point noise. This is the only home for this maths
  // outside Python -- a page that lets someone override one stat rather
  // than only expected minutes needs to recompute here, not just display.
  const GOAL_POINTS = { GK: 10, DEF: 7, MID: 6, FWD: 5 };
  const MAX_X = 200;

  function logGamma(x) {
    const g = 7;
    const c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028,
      771.32342877765313, -176.61502916214059, 12.507343278686905,
      -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - logGamma(1 - x);
    x -= 1;
    let a = c[0];
    const t = x + g + 0.5;
    for (let i = 1; i < g + 2; i++) a += c[i] / (x + i);
    return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
  }

  function poissonPmf(x, mean) {
    if (mean <= 0) return x === 0 ? 1 : 0;
    return Math.exp(-mean + x * Math.log(mean) - logGamma(x + 1));
  }

  function nbinomPmf(x, mean, dispersion) {
    const p = dispersion / (dispersion + mean);
    return Math.exp(logGamma(x + dispersion) - logGamma(dispersion) - logGamma(x + 1) +
      dispersion * Math.log(p) + x * Math.log1p(-p));
  }

  function expectedFloorDiv(mean, k, dispersion) {
    if (mean <= 0 || k <= 0) return 0.0;
    const pmf = new Array(MAX_X + 1);
    for (let x = 0; x <= MAX_X; x++) pmf[x] = nbinomPmf(x, mean, dispersion);
    const cdf = new Array(MAX_X + 1);
    let running = 0;
    for (let x = 0; x <= MAX_X; x++) { running += pmf[x]; cdf[x] = running; }
    let total = 0;
    for (let j = 1; j * k <= MAX_X; j++) {
      const survival = 1.0 - cdf[j * k - 1];
      if (survival < 1e-12) break;
      total += survival;
    }
    return total;
  }

  // `fixture` is one entry of a pool row's `fixtures` array (or that array
  // with overridden fields spread on), i.e. the rate fields from
  // _rate_fields() in scripts/export_app_data.py.
  function pointsGivenMinutes(position, fixture, minutes, sixtyPlus) {
    const scale = minutes / 90.0;
    const disp = fixture.dispersion == null ? 5.0 : fixture.dispersion;
    let pts = sixtyPlus ? 2.0 : 1.0;

    const goals = fixture.goals * scale;
    pts += (GOAL_POINTS[position] || 0) * goals;
    pts += 3.0 * fixture.assists * scale;

    const pHatTrick = goals > 0
      ? 1.0 - (poissonPmf(0, goals) + poissonPmf(1, goals) + poissonPmf(2, goals))
      : 0.0;
    pts += 5.0 * pHatTrick;

    pts -= 3.0 * fixture.ownGoals * scale;
    pts -= 3.0 * fixture.penaltiesMissed * scale;
    pts -= 1.0 * fixture.yellowCards * scale;
    pts -= 3.0 * fixture.redCards * scale;

    if (position === "GK") {
      pts += 2.0 * expectedFloorDiv(fixture.saves * scale, 3, disp);
      pts += 5.0 * fixture.penaltiesSaved * scale;
    }
    if (position === "GK" || position === "DEF") {
      if (sixtyPlus) pts += 5.0 * fixture.pCleanSheet;
      pts -= expectedFloorDiv(fixture.goalsConceded * scale, 2, disp);
    }
    if (position === "DEF") {
      pts += expectedFloorDiv(fixture.clearances * scale, 4, disp);
      pts += expectedFloorDiv(fixture.blocks * scale, 2, disp);
      pts += expectedFloorDiv(fixture.tackles * scale, 2, disp);
    }
    if (position === "MID") pts += 2.0 * fixture.interceptions * scale;
    if (position === "MID" || position === "FWD") {
      pts += expectedFloorDiv(fixture.keyPasses * scale, 2, disp);
      pts += fixture.shotsOnTarget * scale;
    }
    return pts;
  }

  // The page's minutes control is a single known value (team news, or a
  // what-if), not a probability split -- the JS equivalent of Python's
  // deterministic_minutes() + expected_player_points() together.
  function expectedPointsAtMinutes(position, fixture, minutes) {
    if (minutes <= 0) return 0.0;
    return pointsGivenMinutes(position, fixture, minutes, minutes >= 60);
  }

  // Sums a player's fixtures for the gameweek, applying the same minutes
  // value to each -- the same convention the old minutes_curve() used for a
  // double gameweek: one control, summed across both matches.
  function expectedGameweekPoints(position, fixtures, minutes) {
    let total = 0;
    for (const f of fixtures) total += expectedPointsAtMinutes(position, f, minutes);
    return total;
  }

  // ---- Shared per-player override state -------------------------------
  //
  // Keyed by id, not by row instance, so a player's edits are the same
  // whether they were made from the squad section or the pool -- they are
  // the same person, and the squad list is drawn from the pool rows anyway.
  const overrides = new Map();

  function stateFor(id) {
    if (!overrides.has(id)) {
      overrides.set(id, { xmins: POOL_BY_ID.get(id).xmins, fields: {} });
    }
    return overrides.get(id);
  }

  function isAdjusted(id) {
    if (!overrides.has(id)) return false;
    const s = overrides.get(id);
    return s.xmins !== POOL_BY_ID.get(id).xmins || Object.keys(s.fields).length > 0;
  }

  function effectiveFixtures(row, state) {
    const keys = Object.keys(state.fields);
    if (!keys.length) return row.fixtures;
    return row.fixtures.map((f) => ({ ...f, ...state.fields }));
  }

  function pointsFor(row) {
    // Untouched, a player shows the model's own figure rather than a value
    // recomputed here.
    //
    // The two are genuinely different quantities. This page computes points
    // for a player who plays exactly N minutes; the model averages over the
    // distribution of how long he might last. Scoring is non-linear in
    // minutes -- the 60-minute mark is a step, not a slope -- so
    // E[f(minutes)] is not f(E[minutes]). Recomputing by default put the
    // squad total 2.32 points adrift of the projection the squad was
    // actually selected on, with the gap worst for players expected to last
    // 40-60 minutes, exactly where the step bites.
    //
    // Once something *is* overridden the recomputed value is the right one:
    // saying "he plays 75 minutes" replaces a distribution with a certainty,
    // and the number should move to reflect that.
    if (!isAdjusted(row.id)) {
      return row.fixtures.reduce((sum, f) => sum + f.xp, 0);
    }
    const state = stateFor(row.id);
    return expectedGameweekPoints(row.pos, effectiveFixtures(row, state), state.xmins);
  }

  const STAT_FIELDS = [
    { key: "goals", label: "Goals", pos: ["GK", "DEF", "MID", "FWD"] },
    { key: "assists", label: "Assists", pos: ["GK", "DEF", "MID", "FWD"] },
    { key: "saves", label: "Saves", pos: ["GK"] },
    { key: "pCleanSheet", label: "Clean sheet %", pos: ["GK", "DEF"], percent: true },
    { key: "goalsConceded", label: "Goals conceded", pos: ["GK", "DEF"] },
    { key: "clearances", label: "Clearances", pos: ["DEF"] },
    { key: "blocks", label: "Blocks", pos: ["DEF"] },
    { key: "tackles", label: "Tackles", pos: ["DEF"] },
    { key: "interceptions", label: "Interceptions", pos: ["MID"] },
    { key: "keyPasses", label: "Key passes", pos: ["MID", "FWD"] },
    { key: "shotsOnTarget", label: "Shots on target", pos: ["MID", "FWD"] },
  ];
  const fieldsForPosition = (pos) => STAT_FIELDS.filter((f) => f.pos.includes(pos));

  function fixtureLabel(row) {
    if (!row.fixtures.length) return "no fixture";
    return row.fixtures.map((f) => f.opp + " (" + (f.away ? "A" : "H") + ")").join(" + ");
  }

  function earliestKickoff(row) {
    const times = row.fixtures.map((f) => f.kickoff).filter(Boolean).sort();
    return times[0];
  }

  // Builds one player row -- used for both the squad and the pool, so an
  // edit made in either place is the same edit. `onChange` recalculates
  // whatever total the caller cares about (the squad total; nothing for a
  // bare pool row).
  function playerRow(row, opts = {}) {
    const state = stateFor(row.id);
    const li = el("li", "row" +
      (row.proven ? "" : " unproven") +
      (row.status !== "playing" ? " unavailable" : "") +
      (isAdjusted(row.id) ? " adjusted" : ""));
    li.append(el("div", "pos", row.pos));

    const who = el("div", "who");
    const name = el("div", "name");
    name.append(document.createTextNode(row.name));
    if (opts.captain) name.append(el("span", "tag tag-c", "C"));
    if (opts.vice) name.append(el("span", "tag tag-v", "V"));
    who.append(name);

    let meta = row.club + "  \\u00b7  " + fixtureLabel(row);
    if (row.status !== "playing") meta += "  \\u00b7  " + row.status;
    const kickoff = earliestKickoff(row);
    if (opts.showLock && kickoff) meta += "  \\u00b7  locks " + lockLabel(kickoff);
    const metaRow = el("div", "meta");
    if (tier) metaRow.append(tierChip(tier));
    metaRow.append(document.createTextNode(meta));
    who.append(metaRow);
    li.append(who);

    const nums = el("div", "nums");
    const xp = el("div", "xp", fmt(pointsFor(row)));
    nums.append(xp);
    nums.append(el("div", "own", row.own.toFixed(1) + "% owned"));
    const statsToggle = el("button", "statstoggle", "STATS");
    statsToggle.type = "button";
    nums.append(statsToggle);
    li.append(nums);

    function refresh() {
      xp.textContent = fmt(pointsFor(row));
      li.classList.toggle("adjusted", isAdjusted(row.id));
      opts.onChange && opts.onChange();
    }

    li.append(minutesControl(row, state, refresh));

    const panel = statsPanel(row, state, refresh);
    panel.hidden = true;
    statsToggle.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      statsToggle.classList.toggle("on", !panel.hidden);
    });
    li.append(panel);

    return li;
  }

  function minutesControl(row, state, refresh) {
    const wrap = el("div", "mins");
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "90";
    slider.step = "1";
    slider.value = String(state.xmins);
    slider.setAttribute("aria-label", "Expected minutes for " + row.name);

    const readout = el("div", "mins-val", state.xmins + " mins");
    const reset = el("button", "reset", "AUTO");
    reset.type = "button";
    reset.setAttribute("aria-label", "Use the model's estimate for " + row.name);

    function apply(mins) {
      state.xmins = mins;
      slider.value = String(mins);
      const atDefault = mins === POOL_BY_ID.get(row.id).xmins;
      readout.textContent = mins + " mins";
      readout.classList.toggle("set", !atDefault);
      reset.classList.toggle("on", !atDefault);
      refresh();
    }

    slider.addEventListener("input", () => apply(Number(slider.value)));
    reset.addEventListener("click", () => apply(POOL_BY_ID.get(row.id).xmins));
    if (state.xmins !== POOL_BY_ID.get(row.id).xmins) { readout.classList.add("set"); reset.classList.add("on"); }

    wrap.append(slider, readout, reset);
    return wrap;
  }

  function statsPanel(row, state, refresh) {
    const panel = el("div", "stats-panel");
    const grid = el("div", "odds-grid");

    fieldsForPosition(row.pos).forEach((f) => {
      const field = el("div", "odds-field");
      const label = document.createElement("label");
      label.textContent = f.label;
      const inputId = "stat-" + row.id + "-" + f.key;
      label.htmlFor = inputId;

      const input = document.createElement("input");
      input.type = "number";
      input.id = inputId;
      input.inputMode = "decimal";
      input.step = f.percent ? "1" : "0.01";
      input.min = "0";
      const baseline = row.fixtures[0] ? row.fixtures[0][f.key] : 0;
      const current = f.key in state.fields ? state.fields[f.key] : baseline;
      input.value = f.percent ? Math.round(current * 100) : current.toFixed(2);

      input.addEventListener("change", () => {
        let v = parseFloat(input.value);
        if (!Number.isFinite(v) || v < 0) v = 0;
        state.fields[f.key] = f.percent ? v / 100 : v;
        refresh();
      });

      field.append(label, input);
      grid.append(field);
    });

    const resetRow = el("div");
    const reset = el("button", "reset on", "RESET STATS");
    reset.type = "button";
    reset.style.visibility = "visible";
    reset.addEventListener("click", () => {
      state.fields = {};
      fieldsForPosition(row.pos).forEach((f) => {
        const input = panel.querySelector("#stat-" + row.id + "-" + f.key);
        const baseline = row.fixtures[0] ? row.fixtures[0][f.key] : 0;
        input.value = f.percent ? Math.round(baseline * 100) : baseline.toFixed(2);
      });
      refresh();
    });
    resetRow.append(reset);

    panel.append(grid, resetRow);
    return panel;
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

  const squadRows = DATA.squad.playerIds.map((id) => POOL_BY_ID.get(id));

  // Lockout is rolling -- each player locks at their own kickoff, not at one
  // gameweek deadline. Counting down to the first fixture in the round would
  // cost hours of usable time, and those are the hours when team news lands.
  const squadLocks = squadRows
    .map(earliestKickoff).filter(Boolean).map((k) => new Date(k)).sort((a, b) => a - b);
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

  // Squad, in formation order. Every row carries the same minutes control
  // and stats panel as the pool -- an edit here and an edit to the same
  // player found via the pool are the same edit, because both read and
  // write stateFor(row.id).
  const squadList = document.getElementById("squad");
  const order = { GK: 0, DEF: 1, MID: 2, FWD: 3 };

  const squadOrder = squadRows
    .slice()
    .sort((a, b) => order[a.pos] - order[b.pos] || pointsFor(b) - pointsFor(a));

  function recalcTotal() {
    const base = squadRows.reduce((sum, row) => sum + pointsFor(row), 0);
    const captain = POOL_BY_ID.get(DATA.squad.captain);
    const clubs = DATA.squad.clubs.reduce((s, c) => s + c.xp, 0);
    const total = base + pointsFor(captain) + clubs;

    document.getElementById("total").textContent = fmt(total);
    const anyAdjusted = squadRows.some((row) => isAdjusted(row.id));
    const shift = total - DATA.squad.total;
    document.getElementById("totalnote").textContent = !anyAdjusted
      ? "projected points, captain doubled"
      : (shift >= 0 ? "+" : "") + shift.toFixed(2) + " vs the model's estimate";
  }

  squadOrder.forEach((row) => {
    const isCaptain = row.id === DATA.squad.captain;
    const isVice = row.id === DATA.squad.vice;
    squadList.append(playerRow(row, {
      captain: isCaptain, vice: isVice, showLock: true, onChange: recalcTotal,
    }));
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

  const tierKey = document.getElementById("tierkey");
  if (tierKey) {
    tierKey.append(document.createTextNode("fixture "));
    for (let t = 1; t <= 5; t++) tierKey.append(tierChip(t));
    tierKey.append(document.createTextNode(" 1 easiest, 5 hardest"));
  }

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

  // Full player pool: every selectable player, not just a top 20, with a
  // position filter, free-text search and a sort choice. Capped at
  // POOL_SHOWN per filter/search combination with a "show all" button --
  // the same disclosure pattern as the club table above -- so the initial
  // render stays light even for a 600-player division on a phone.
  const filters = document.getElementById("filters");
  const pool = document.getElementById("pool");
  const poolSearchInput = document.getElementById("poolsearch");
  const poolSortSelect = document.getElementById("poolsort");
  const morePool = document.getElementById("morepool");
  const POOL_SHOWN = 30;

  let active = "MID";
  let poolSearch = "";
  let poolSort = "xp";
  let poolExpanded = false;

  const SORTERS = {
    xp: (a, b) => pointsFor(b) - pointsFor(a),
    own: (a, b) => b.own - a.own,
    name: (a, b) => a.name.localeCompare(b.name),
  };

  function poolMatches() {
    const q = poolSearch.trim().toLowerCase();
    const rows = DATA.pool.filter((row) => row.pos === active);
    const filtered = q
      ? rows.filter((row) => row.name.toLowerCase().includes(q) || row.club.toLowerCase().includes(q))
      : rows;
    return filtered.slice().sort(SORTERS[poolSort]);
  }

  function renderPool() {
    const matches = poolMatches();
    const shown = poolExpanded ? matches : matches.slice(0, POOL_SHOWN);
    pool.replaceChildren();
    shown.forEach((row) => pool.append(playerRow(row)));

    document.getElementById("poolcount").textContent =
      matches.length + (poolSearch ? " match" + (matches.length === 1 ? "" : "es") : " selectable");
    morePool.hidden = matches.length <= POOL_SHOWN;
    morePool.textContent = poolExpanded ? "Show fewer" : "Show all " + matches.length;
    morePool.setAttribute("aria-expanded", String(poolExpanded));
  }

  ["GK", "DEF", "MID", "FWD"].forEach((pos) => {
    const b = el("button", "chip", pos);
    b.type = "button";
    b.setAttribute("aria-pressed", String(pos === active));
    b.addEventListener("click", () => {
      active = pos;
      poolExpanded = false;
      filters.querySelectorAll(".chip").forEach((c) =>
        c.setAttribute("aria-pressed", String(c.textContent === pos)));
      renderPool();
    });
    filters.append(b);
  });

  poolSearchInput.addEventListener("input", () => {
    poolSearch = poolSearchInput.value;
    poolExpanded = false;
    renderPool();
  });
  poolSortSelect.addEventListener("change", () => {
    poolSort = poolSortSelect.value;
    renderPool();
  });
  morePool.addEventListener("click", () => {
    poolExpanded = !poolExpanded;
    renderPool();
  });

  renderPool();

  // ---- Club repricing -------------------------------------------------
  //
  // Club maths ported from goals.py and expected.py, verified against the
  // Python implementation for all 72 fixtures (largest disagreement 6e-9).
  // Reuses poissonPmf from the player-scoring port above rather than a
  // second copy -- same function, (count, rate) either way.
  const MAX_GOALS = 15;

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
