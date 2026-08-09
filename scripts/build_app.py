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
    /* Taken from the EFL's own division marks rather than chosen: #001489
       appears in all four, with gold, silver and red distinguishing the
       Championship, League One and League Two. The navy is too dark to read
       as an accent on a dark ground, so it does what it does on the official
       site -- a solid band behind white -- while a brightened relative
       carries anything interactive. */
    --navy: #001489;
    --navy-lift: #4C6FE8;
    --gold: #B69B42;
    --silver: #8E8F8F;
    /* League Two's #BA0C2F is dark enough to vanish against a dark
       ground -- 0.17 luminance against 0.50 for gold -- so it is lifted
       here and kept exact in the light theme. */
    --red: #E42A45;

    --ink: #070B1C;
    --surface: #101736;
    --raised: #182044;
    --line: #232C56;
    --text: #E8EBF6;
    --mist: #8E97BC;
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
    --t5: #6E2440;
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
      --ink: #EEF1F8;
      --surface: #FFFFFF;
      --raised: #F7F9FD;
      --line: #D5DCEC;
      --text: #0A1230;
      --mist: #5A6690;
      --navy-lift: #001489;
      --gold: #8A7328;
      --silver: #63646B;
      --red: #9A0A26;
      --floodlight: #B87516;
      --pitch: #35704A;
      --clay: #A8452F;
      /* Deepened for contrast against a white ground. */
      --t1: #3B8A4C;
      --t2: #6E8B34;
      --t3: #A87F1E;
      --t4: #A85628;
      --t5: #5C1B34;
      --t1-ink: #FFFFFF;
      --t2-ink: #FFFFFF;
      --t3-ink: #FFFFFF;
      --t4-ink: #FFFFFF;
      --t5-ink: #FFFFFF;
    }
  }
  /* The viewer's toggle stamps data-theme on the root and must win over the
     media query in both directions, so each theme is restated in full. Listing
     only the differences here would leave a toggled page half-dressed in the
     other theme's colours. */
  :root[data-theme="dark"] {
    --ink: #070B1C; --surface: #101736; --raised: #182044; --line: #232C56;
    --text: #E8EBF6; --mist: #8E97BC;
    --navy-lift: #4C6FE8; --gold: #B69B42; --silver: #8E8F8F; --red: #E42A45;
    --floodlight: #E9A13B; --pitch: #4A8F63; --clay: #C2604E;
    --t1: #4E9E5F; --t2: #86A343; --t3: #C29A33; --t4: #BE6D3C; --t5: #6E2440;
    --t1-ink: #08120B; --t2-ink: #0C1206; --t3-ink: #14100A;
    --t4-ink: #FBEFE8; --t5-ink: #FCEDEA;
  }
  :root[data-theme="light"] {
    --ink: #EEF1F8; --surface: #FFFFFF; --raised: #F7F9FD; --line: #D5DCEC;
    --text: #0A1230; --mist: #5A6690;
    --navy-lift: #001489; --gold: #8A7328; --silver: #63646B; --red: #9A0A26;
    --floodlight: #B87516; --pitch: #35704A; --clay: #A8452F;
    --t1: #3B8A4C; --t2: #6E8B34; --t3: #A87F1E; --t4: #A85628; --t5: #5C1B34;
    --t1-ink: #FFFFFF; --t2-ink: #FFFFFF; --t3-ink: #FFFFFF;
    --t4-ink: #FFFFFF; --t5-ink: #FFFFFF;
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
    background: var(--navy);
    color: #FFFFFF;
    border-bottom: 3px solid var(--navy-lift);
    padding: 0.875rem 1rem 0.8125rem;
    margin: 0 -1rem 1.5rem;
  }
  header .label { color: rgba(255, 255, 255, 0.62); }
  header .deadline { color: rgba(255, 255, 255, 0.68); }
  header h1 { color: #FFFFFF; }
  header .countdown { color: #FFFFFF; }
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
  .row.div-CH { border-left-color: var(--gold); }
  .row.div-L1 { border-left-color: var(--silver); }
  .row.div-L2 { border-left-color: var(--red); }
  .row.unproven { opacity: 0.82; }
  .row.club-row { border-left-color: var(--floodlight); }
  .row.club-row.div-CH { border-left-color: var(--gold); }
  .row.club-row.div-L1 { border-left-color: var(--silver); }
  .row.club-row.div-L2 { border-left-color: var(--red); }

  .viewnav {
    display: flex;
    gap: 2px;
    margin: 0 -1rem 1.25rem;
    background: var(--navy);
    padding: 0 1rem 0.625rem;
  }
  .viewnav button {
    flex: 1;
    font-family: var(--ui);
    font-size: 0.8125rem;
    font-weight: 650;
    letter-spacing: 0.01em;
    padding: 0.5rem;
    min-height: 2.5rem;
    background: rgba(255, 255, 255, 0.09);
    color: rgba(255, 255, 255, 0.68);
    border: none;
    border-radius: 3px;
    cursor: pointer;
  }
  .viewnav button[aria-selected="true"] {
    background: #FFFFFF;
    color: var(--navy);
  }
  .viewnav button:focus-visible { outline: 2px solid #FFFFFF; outline-offset: 2px; }

  .slot {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.75rem;
    background: var(--surface);
    border-left: 3px dashed var(--line);
    padding: 0.6875rem 0.875rem;
    width: 100%;
    text-align: left;
    font-family: var(--ui);
    font-size: var(--step-0);
    color: var(--mist);
    cursor: pointer;
  }
  .slot:focus-visible { outline: 2px solid var(--navy-lift); outline-offset: -2px; }
  .slot .pos { color: var(--mist); }
  .slot-add { font-family: var(--mono); font-size: 0.75rem; color: var(--navy-lift); }

  .drop {
    font-family: var(--mono);
    font-size: 0.625rem;
    font-weight: 700;
    background: none;
    border: 1px solid var(--line);
    border-radius: 2px;
    color: var(--mist);
    padding: 0.25rem 0.375rem;
    min-height: 1.75rem;
    margin-left: 0.375rem;
    cursor: pointer;
  }
  .drop:hover, .drop:focus-visible { color: var(--clay); border-color: var(--clay); }

  .plan-warn {
    font-size: 0.75rem;
    color: var(--clay);
    margin-top: 0.375rem;
  }
  .picker-head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }
  .picker-head input {
    flex: 1;
    font-family: var(--ui);
    font-size: 0.875rem;
    padding: 0.5rem 0.625rem;
    min-height: 2.5rem;
    background: var(--raised);
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 3px;
  }
  .row.pickable { cursor: pointer; }
  .row.blocked { opacity: 0.4; cursor: not-allowed; }

  .divkey {
    display: flex;
    gap: 0.75rem;
    font-size: 0.625rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--mist);
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
  }
  .divkey span { display: inline-flex; align-items: center; gap: 0.3125rem; }
  .divkey i {
    width: 0.75rem;
    height: 3px;
    border-radius: 1px;
    display: inline-block;
  }

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
    background: var(--navy-lift);
    color: #FFFFFF;
    border-color: var(--navy-lift);
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

  .own.elite-up { color: var(--pitch); }
  .own.elite-down { color: var(--clay); }

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

  /* ============ FEFL CLUB -- desktop app shell ============
     Everything above is phone-first, capped to a single 40rem column.
     This block rebuilds the page as a full-width, four-tab desktop app:
     a brand + nav top bar, and each tab a master list beside a detail
     panel, with the list scrolling on its own rather than the page.
     Presentation only -- the scoring, override and planner logic are
     untouched and the JS smoke test still covers them. */

  .brand {
    font-weight: 800;
    letter-spacing: 0.02em;
    font-size: var(--step-1);
    color: #FFFFFF;
    background: var(--navy-lift);
    padding: 0.4rem 0.9rem;
    border-radius: 4px;
    white-space: nowrap;
  }
  header.topbar { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
  .gwstrip {
    width: 100%;
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    margin-top: 0.35rem;
  }
  .gwstrip .dot { opacity: 0.5; color: #FFFFFF; }
  .gwstrip .countdown { margin-left: auto; }

  .split { display: flex; flex-direction: column; gap: 1.25rem; }
  .listcol { min-width: 0; }
  .listcount { margin-bottom: 0.5rem; }
  .detailcol {
    min-width: 0;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 1rem;
  }
  .detailcol.wide { max-width: 56rem; }
  .detail-head {
    display: flex; align-items: center; justify-content: space-between;
    gap: 0.75rem; margin-bottom: 0.75rem;
    padding-bottom: 0.5rem; border-bottom: 1px solid var(--line);
  }
  .detail-head h2 { font-size: var(--step-1); margin: 0; }
  .detail-empty { color: var(--mist); font-size: 0.9rem; line-height: 1.6; }
  .detail-empty p { margin: 0 0 0.75rem; }
  .detail-player .name { font-size: var(--step-1); }
  .blind-note { margin-top: 1.5rem; }

  .row.selected { outline: 2px solid var(--floodlight); outline-offset: -2px; }

  /* Team Planner: chips box + formation, and the squad on a pitch-green
     ground so the landing tab reads as a team sheet. */
  .planner-head {
    display: flex; align-items: stretch; justify-content: space-between;
    gap: 0.75rem; margin-bottom: 0.75rem; flex-wrap: wrap;
  }
  .chips-box {
    background: var(--surface); border: 1px solid var(--line);
    border-left: 3px solid var(--floodlight); border-radius: 4px;
    padding: 0.5rem 0.75rem;
  }
  .chips-list { font-family: var(--mono); font-size: 0.8rem; margin-top: 0.2rem; }
  .pitch-formation {
    font-size: 0.8rem; color: var(--mist);
    display: flex; align-items: center; gap: 0.4rem;
  }
  .pitch-formation select {
    font-family: var(--ui); font-weight: 650; padding: 0.4rem 0.5rem;
    background: var(--raised); color: var(--text);
    border: 1px solid var(--line); border-radius: 3px;
  }
  /* A green ground with mown stripes; the markings are drawn as bordered
     boxes over the top (all percentage-based so they scale with the pitch). */
  .pitch {
    position: relative; overflow: hidden;
    border: 1px solid var(--line); border-radius: 8px;
    aspect-ratio: 5 / 7; height: min(68vh, 34rem); width: auto; max-width: 100%;
    margin: 0 auto;
    background:
      repeating-linear-gradient(180deg,
        rgba(255,255,255,0.06) 0 8%, rgba(0,0,0,0.06) 8% 16%),
      var(--pitch);
  }
  .pitch-turf {
    position: absolute; inset: 0.6rem; pointer-events: none; border-radius: 3px;
  }
  .pitch-turf, .mk-circle, .mk-box, .mk-goal {
    border: 2px solid rgba(255,255,255,0.45);
  }
  .mk-half { position: absolute; left: 0; right: 0; top: 50%;
    border-top: 2px solid rgba(255,255,255,0.45); }
  .mk-circle { position: absolute; left: 50%; top: 50%; width: 26%; aspect-ratio: 1;
    transform: translate(-50%,-50%); border-radius: 50%; }
  .mk-box { position: absolute; left: 50%; transform: translateX(-50%);
    width: 56%; height: 15%; }
  .mk-box-top { top: 0; border-top: none; }
  .mk-box-bot { bottom: 0; border-bottom: none; }
  .mk-goal { position: absolute; left: 50%; transform: translateX(-50%);
    width: 28%; height: 6%; }
  .mk-goal-top { top: 0; border-top: none; }
  .mk-goal-bot { bottom: 0; border-bottom: none; }

  .clubs-head { margin-top: 1rem; }

  /* ---- Team Planner: pitch, picker, popup --------------------------- */
  .planner-body { display: flex; flex-direction: column; gap: 1.5rem; }
  .pitchcol { min-width: 0; }
  .pickcol { min-width: 0; }
  @media (min-width: 64rem) {
    /* The pitch is sized by its own height; the picker takes the rest, so it
       fills roughly half of a wide screen. */
    .planner-body { flex-direction: row; align-items: flex-start; }
    .pitchcol { flex: 0 1 auto; min-width: 0; }
    .pickcol { flex: 1 1 0; min-width: 26rem; position: sticky; top: 5.5rem; }
    /* Fill the viewport height; width follows from the 5:7 ratio, so a taller
       pitch is also a wider one. */
    .pitch { height: min(calc(100vh - 7rem), 58rem); }
  }

  /* Players and clubs float above the turf in formation lines. */
  .pitch-lines {
    position: absolute; inset: 0; z-index: 1;
    display: flex; flex-direction: column; justify-content: space-evenly;
    gap: 0.3rem; padding: 0.6rem 0.75rem;
  }
  .pitch-line { display: flex; justify-content: space-around; align-items: flex-start;
    gap: 0.4rem; flex-wrap: wrap; }
  .shirt {
    width: clamp(5.4rem, 12vw, 8.5rem);
    background: rgba(7,11,28,0.5); border-radius: 8px;
    padding: 0.25rem 0.35rem; cursor: pointer; text-align: center; color: #fff;
  }
  .shirt.captained { box-shadow: 0 0 0 2px var(--floodlight); }
  .shirt.adjusted .kit { outline: 2px solid #8B5CF6; outline-offset: 1px; }

  /* A jersey drawn with clip-path, tinted the club's colour, with xPts on it. */
  .kit-wrap {
    position: relative; width: clamp(3rem, 6.5vw, 4.6rem);
    margin: 0 auto 0.15rem; aspect-ratio: 1;
  }
  .kit {
    position: absolute; inset: 0; background: #6b7280;
    clip-path: polygon(32% 0, 42% 8%, 58% 8%, 68% 0, 100% 14%, 86% 40%,
      78% 30%, 78% 100%, 22% 100%, 22% 30%, 14% 40%, 0 14%);
  }
  .kit-trim {
    position: absolute; inset: 0;
    clip-path: polygon(42% 8%, 58% 8%, 57% 16%, 43% 16%);
  }
  .kit-pts {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    padding: 14% 22% 0;
    font-family: var(--mono); font-weight: 800; line-height: 1;
    font-size: clamp(0.8rem, 1.8vw, 1.3rem);
  }
  .kit.ghost {
    background: none; clip-path: none; border-radius: 4px;
    border: 1.5px dashed rgba(255,255,255,0.5);
  }
  .shirt-name {
    font-weight: 700; font-size: clamp(0.74rem, 1.5vw, 1rem); line-height: 1.1;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .shirt-opp {
    font-family: var(--mono); font-size: 0.62rem; color: rgba(255,255,255,0.65);
    letter-spacing: 0.03em; margin-top: 0.05rem;
  }
  .shirt-sub {
    font-family: var(--mono); font-size: 0.72rem; color: rgba(255,255,255,0.8);
    display: flex; align-items: center; justify-content: center; gap: 0.25rem;
    margin-top: 0.15rem;
  }
  .mins-in {
    width: 2.6rem; font-family: var(--mono); font-size: 0.78rem; font-weight: 700;
    text-align: center; padding: 0.1rem 0.15rem; border-radius: 4px;
    background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.35); color: #fff;
  }
  .mins-in.edited { border-color: #8B5CF6; color: #d7c4ff; font-weight: 800; }
  .shirt-ctl { display: flex; justify-content: center; gap: 0.3rem; margin-top: 0.35rem; }
  .sbtn {
    font-family: var(--mono); font-weight: 800; font-size: 0.7rem; line-height: 1;
    min-width: 1.7rem; height: 1.6rem; border-radius: 4px; padding: 0 0.35rem; flex: 0 0 auto;
    background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.35);
    color: #fff; cursor: pointer;
  }
  .sbtn:hover { background: rgba(255,255,255,0.22); }
  .cap-btn.on { background: var(--floodlight); border-color: var(--floodlight); color: var(--ink); }
  .shirt.empty {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 0.25rem; padding: 0.5rem 0.35rem;
  }
  .shirt-add { font-family: var(--mono); font-size: 0.68rem; color: #fff; }

  .pickertabs { display: flex; gap: 0.4rem; margin-bottom: 0.6rem; background: none; padding: 0; }
  .pickertabs button {
    flex: 0 0 auto; font-family: var(--ui); font-weight: 650; font-size: 0.85rem;
    padding: 0.4rem 1.1rem; border: 1px solid var(--line); border-radius: 4px;
    background: var(--surface); color: var(--mist); cursor: pointer; min-height: 2.25rem;
  }
  .pickertabs button[aria-selected="true"] {
    background: var(--navy-lift); color: #FFFFFF; border-color: var(--navy-lift);
  }
  /* Picked rows keep their value shading (no dimming); a left accent plus the
     disabled + button is enough to show they are already in the squad. */
  .dtable tbody tr.in-squad td:first-child { box-shadow: inset 3px 0 0 var(--navy-lift); }

  .modal {
    position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55);
    display: flex; align-items: flex-start; justify-content: center;
    padding: 4rem 1rem; overflow: auto;
  }
  /* The class sets display:flex, which would otherwise beat the hidden
     attribute and leave the overlay permanently covering the page. */
  .modal[hidden] { display: none; }
  .modal-box {
    background: var(--ink); border: 1px solid var(--line); border-radius: 8px;
    padding: 1.25rem; max-width: 34rem; width: 100%;
  }
  .modal-actions { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .chip.on { background: var(--floodlight); color: var(--ink); border-color: var(--floodlight); }
  .chip.danger { color: var(--clay); border-color: var(--clay); }

  /* ---- Data tables (Player / Team projections, planner picker) -------
     Dense rows -- the wasted vertical space of the card list is gone.
     Sticky headers so columns stay labelled while the body scrolls. */
  .tablewrap { width: 100%; }
  /* The table pane shrinks to the table, so the scrollbar sits right after the
     last column instead of across a gulf of empty space. Capped at the full
     width, beyond which the columns scroll horizontally. */
  .scroller.fitcontent { width: fit-content; max-width: 100%; }

  /* The breakdown lives beside the table on a wide screen and drops in below
     each row when there is not room for a side panel (half-screen). */
  .players-body { display: flex; gap: 1.5rem; align-items: flex-start; }
  .players-body > .tablewrap { flex: 1 1 auto; width: 100%; min-width: 0; }
  .players-body table.dtable { width: 100%; }
  .players-body > .detailcol { display: none; }
  @media (min-width: 96rem) {
    /* Table fills the left half so its scrollbar lands at the screen's middle;
       the breakdown panel fills the right half. */
    .players-body > .tablewrap { flex: 0 0 50%; }
    .players-body > .detailcol {
      display: block;
      flex: 1 1 auto;
      position: sticky;
      top: 5.5rem;
      max-height: calc(100vh - 7rem);
      overflow: auto;
    }
  }

  /* League badge in the Team Projections table. */
  .divbadge { font-family: var(--mono); font-weight: 700; font-size: 0.7rem; }
  .divbadge.CH { color: var(--gold); }
  .divbadge.L1 { color: var(--silver); }
  .divbadge.L2 { color: var(--red); }

  /* Club xPts, term by term, with an editable odds price on each line. */
  .compedits { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 0.6rem; }
  .compedit {
    display: flex; align-items: center; gap: 0.55rem;
    font-family: var(--mono); font-size: 1.1rem;
    font-variant-numeric: tabular-nums;
  }
  .compedit-lab {
    flex: 1 1 auto; min-width: 8rem;
    font-family: var(--ui); font-weight: 650; font-size: 1.05rem;
  }
  .compedit-mult { color: var(--mist); }
  .compedit-eq { color: var(--mist); }
  .compedit-odds { min-width: 3.2rem; text-align: right; color: var(--mist); }
  .compedit-out {
    min-width: 3.6rem; text-align: right;
    font-weight: 700; color: var(--pitch);
  }
  .compedit-out.big { font-size: 1.5rem; color: var(--floodlight); }
  .compedit.comptotal {
    margin-top: 0.3rem; padding-top: 0.45rem;
    border-top: 1px solid var(--line);
  }
  .oddsinput {
    width: 4.2rem; font-family: var(--mono); font-size: 1.05rem; text-align: right;
    padding: 0.25rem 0.4rem; background: var(--surface); color: var(--text);
    border: 1px solid var(--line); border-radius: 3px;
    appearance: textfield; -moz-appearance: textfield;
  }
  .oddsinput::-webkit-outer-spin-button,
  .oddsinput::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  .oddsinput.overridden-input {
    border-color: #8B5CF6; background: rgba(139, 92, 246, 0.20); font-weight: 800;
  }

  /* The spacer column between Opp and xPts soaks up the slack, so the data
     columns stay tight and the table still reaches the divide. */
  .dtable td.gapcol { width: 100%; min-width: 1.5rem; max-width: none; }

  /* Threshold filter bar. */
  .filterbar {
    display: flex; flex-wrap: wrap; gap: 0.35rem 0.8rem;
    align-items: center; margin-bottom: 0.6rem;
  }
  .filterbar .fitem {
    display: flex; align-items: center; gap: 0.3rem;
    font-size: 0.72rem; color: var(--mist); font-family: var(--mono);
  }
  .filterbar input {
    width: 3.4rem; font-family: var(--mono); font-size: 0.75rem;
    text-align: right; padding: 0.2rem 0.3rem;
    background: var(--surface); color: var(--text);
    border: 1px solid var(--line); border-radius: 3px;
    appearance: textfield; -moz-appearance: textfield;
  }
  .filterbar input::-webkit-outer-spin-button,
  .filterbar input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  /* Columns size to their content rather than stretching to fill the panel,
     so figures sit tight to their headers instead of drifting off to the
     right with dead space beside them. */
  table.dtable {
    width: auto;
    border-collapse: collapse;
    font-size: 0.8125rem;
  }
  .dtable thead th {
    position: sticky; top: 0; z-index: 1;
    background: var(--raised);
    color: var(--mist);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    font-size: 0.72rem;
    text-align: left;
    padding: 0.4rem 0.5rem;
    border-bottom: 1px solid var(--line);
    white-space: nowrap;
  }
  .dtable th.num, .dtable td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    font-family: var(--mono);
  }
  .dtable th.sortable { cursor: pointer; user-select: none; }
  .dtable th.sortable:hover { color: var(--text); }
  .dtable th.sorted { color: var(--floodlight); }
  .dtable th .arrow { font-size: 0.6rem; }
  .dtable tbody td {
    padding: 0.45rem 0.4rem;
    border-bottom: 1px solid var(--line);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 13rem;
  }
  /* Cap the text columns so the figures are never pushed off the panel, and
     mute them so the player name still leads the eye. */
  .dtable td[data-col="name"] { max-width: 12rem; }
  .dtable td[data-col="club"] { max-width: 8rem; color: var(--mist); }
  /* Opponent is never cropped -- it sizes to the full club name. */
  .dtable td[data-col="opp"] { color: var(--mist); }
  /* The player's name is the anchor for the eye -- larger and heavier than
     the surrounding figures so a row reads name-first. */
  .dtable td .pname {
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--text);
  }
  .dtable tbody tr.clickable { cursor: pointer; }
  .dtable tbody tr.clickable:hover { background: var(--raised); }
  .dtable tbody tr.selected-row { background: var(--raised); }
  .dtable tbody tr.unproven { opacity: 0.7; }
  .dtable tbody tr.adjusted td:first-child { box-shadow: inset 3px 0 0 var(--floodlight); }
  .dtable tr.expand td { background: var(--raised); white-space: normal; padding: 0.75rem; }
  .breakdown { display: flex; flex-direction: column; gap: 0.5rem; }

  /* Inline, always-editable numeric cell -- reads as text until hovered or
     focused, so the grid stays clean but every figure can be overridden. */
  .cellinput {
    width: 3.1rem;
    font-family: var(--mono);
    font-size: 0.8125rem;
    text-align: right;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    color: inherit;
    padding: 0.1rem 0.25rem;
    font-variant-numeric: tabular-nums;
    appearance: textfield;
    -moz-appearance: textfield;
  }
  /* Drop the spin buttons -- they steal the space that clipped the second
     decimal. */
  .cellinput::-webkit-outer-spin-button,
  .cellinput::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  .cellinput:hover { border-color: var(--line); }
  .cellinput:focus { border-color: var(--navy-lift); outline: none; background: var(--ink); }

  /* An overridden figure: a distinct violet that stands apart from the green
     rank ramp and stays clear of red/green confusion. */
  .dtable td.overridden {
    background: rgba(139, 92, 246, 0.34) !important;
    box-shadow: inset 0 0 0 2px #8B5CF6;
  }
  .dtable td.overridden .cellinput { font-weight: 800; }

  /* Multi-select club filter. */
  .multiselect { position: relative; }
  .ms-panel {
    position: absolute; z-index: 20; top: 100%; left: 0; margin-top: 2px;
    min-width: 14rem; max-height: 16rem; overflow: auto;
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 4px; padding: 0.4rem;
  }
  .ms-panel label {
    display: flex; align-items: center; gap: 0.45rem;
    padding: 0.2rem 0.3rem; font-size: 0.8rem; cursor: pointer; white-space: nowrap;
  }
  .ms-panel label:hover { background: var(--raised); }
  .ms-panel .msdiv { border-top: 1px solid var(--line); margin: 0.3rem 0; }

  /* Big add / remove control for the planner picker table. */
  .addbtn {
    font-family: var(--mono); font-weight: 800; font-size: 1.05rem; line-height: 1;
    width: 1.7rem; height: 1.7rem; border-radius: 4px;
    background: var(--navy-lift); color: #FFFFFF; border: none; cursor: pointer;
  }
  .addbtn:disabled { background: var(--line); color: var(--mist); cursor: not-allowed; }

  /* A search box that sits inline in a toolrow. */
  .toolrow .listcount { margin: 0 0 0 auto; align-self: center; }

  @media (min-width: 64rem) {
    .wrap { max-width: none; padding: 0 1.75rem 3rem; }

    header.topbar {
      margin: 0 -1.75rem 1.25rem;
      padding: 0.85rem 1.75rem 0.8rem;
      flex-wrap: nowrap;
    }
    .gwstrip { width: auto; margin-top: 0; margin-left: auto; font-size: 0.8rem; }

    /* The nav sits inline in the top bar, tabs at their natural width. */
    .viewnav {
      margin: 0; padding: 0; background: none; gap: 0.4rem; flex: 1 1 auto;
    }
    .viewnav button {
      flex: 0 0 auto; padding: 0.5rem 1.1rem; font-size: 0.9rem;
      background: rgba(255, 255, 255, 0.10);
    }

    /* Two- and three-column tab bodies. Each list scrolls in its own
       pane (calc keeps it inside the viewport) so the wheel moves the
       list, not the whole page; the detail panel sticks alongside. */
    .split { flex-direction: row; align-items: start; gap: 1.5rem; }
    .split > .listcol { flex: 1 1 0; }
    .split > .detailcol { flex: 1 1 0; }
    .split-3 > .listcol { flex: 1.15 1 0; }

    .scroller {
      max-height: calc(100vh - 12rem);
      overflow: auto;
      padding-right: 0.4rem;
    }
    /* Table and detail panel meet in the middle of the screen. The table's
       columns stay content-sized, so the core figures sit on the left and the
       stat breakdown fills rightward to the divide; a horizontal scrollbar is
       the safety net if a narrow window cannot fit every column. */
    .split.wide-list > .listcol { flex: 1 1 0; }
    .split.wide-list > .detailcol { flex: 1 1 0; }
    .split > .detailcol {
      position: sticky; top: 5.5rem;
      max-height: calc(100vh - 7rem); overflow-y: auto;
    }
  }
</style>

<div class="wrap">
  <header class="topbar">
    <div class="brand">FEFL CLUB</div>
    <nav class="viewnav" role="tablist" aria-label="Sections">
      <button id="tab-planner" role="tab" aria-selected="true">Team Planner</button>
      <button id="tab-players" role="tab" aria-selected="false">Player Projections</button>
      <button id="tab-clubs" role="tab" aria-selected="false">Team Projections</button>
      <button id="tab-history" role="tab" aria-selected="false">Historical Data</button>
    </nav>
    <div class="gwstrip">
      <span class="label" id="gw"></span>
      <span class="dot">&middot;</span>
      <span class="deadline" id="deadline"></span>
      <span class="countdown" id="countdown" aria-live="polite"></span>
    </div>
  </header>

  <!-- ===== Team Planner (landing) ===== -->
  <div id="view-planner" class="view">
    <div class="planner-body">
      <div class="pitchcol">
        <div class="planner-head">
          <div class="chips-box">
            <div class="label">Chips available</div>
            <div class="chips-list" id="chipslist">One Club &middot; Max Captain</div>
          </div>
          <label class="pitch-formation">Formation
            <select id="planformation" aria-label="Formation"></select>
          </label>
        </div>
        <div class="summary">
          <div>
            <div class="total" id="plantotal">0.00</div>
            <div class="total-note" id="plannote">nothing picked yet</div>
          </div>
          <div>
            <button class="chip" id="planseed" type="button">Fill from model</button>
            <button class="chip" id="planclear" type="button">Clear</button>
          </div>
        </div>
        <div class="plan-warn" id="planwarn"></div>
        <div class="pitch">
          <div class="pitch-turf" aria-hidden="true">
            <span class="mk-half"></span>
            <span class="mk-circle"></span>
            <span class="mk-box mk-box-top"></span>
            <span class="mk-box mk-box-bot"></span>
            <span class="mk-goal mk-goal-top"></span>
            <span class="mk-goal mk-goal-bot"></span>
          </div>
          <div class="pitch-lines" id="pitchlines"></div>
        </div>
      </div>
      <aside class="pickcol">
        <div class="viewnav pickertabs" role="tablist">
          <button id="picktab-players" role="tab" aria-selected="true">Players</button>
          <button id="picktab-teams" role="tab" aria-selected="false">Teams</button>
        </div>
        <div class="toolrow">
          <div class="filters" id="plfilters" role="group" aria-label="Filter by position"></div>
          <div class="filters" id="plleague" role="group" aria-label="Filter by league"></div>
          <div class="filters" id="plha" role="group" aria-label="Home or away"></div>
          <div class="multiselect">
            <button class="chip" id="plclubbtn" type="button" aria-haspopup="true" aria-expanded="false">All clubs</button>
            <div class="ms-panel" id="plclubpanel" hidden></div>
          </div>
          <input class="search" id="plsearch" type="search" placeholder="Search&hellip;">
        </div>
        <div class="filterbar" id="plfilterbar"></div>
        <div class="tablewrap scroller" id="pickertable"></div>
      </aside>
    </div>
    <div class="modal" id="planmodal" hidden>
      <div class="modal-box" id="planmodalbox"></div>
    </div>
  </div>

  <!-- ===== Player Projections ===== -->
  <div id="view-players" class="view" hidden>
    <div class="toolrow">
      <div class="filters" id="filters" role="group" aria-label="Filter by position"></div>
      <div class="multiselect">
        <button class="sortselect" id="poolclubbtn" type="button" aria-expanded="false">All clubs</button>
        <div class="ms-panel" id="poolclubpanel" hidden></div>
      </div>
      <input class="search" id="poolsearch" type="search" placeholder="Search player&hellip;" aria-label="Search the player pool">
      <button class="chip" id="pooloverbtn" type="button" aria-pressed="false">Overridden</button>
      <button class="chip" id="poolresetbtn" type="button">Reset all</button>
    </div>
    <div class="filterbar" id="poolfilters"></div>
    <div class="listcount label" id="poolcount"></div>
    <div class="players-body">
      <div class="tablewrap scroller" id="pooltable"></div>
      <aside class="detailcol" id="playerdetail">
        <div class="detail-head"><h2>Player breakdown</h2></div>
        <div class="detail-empty" id="playerdetailempty">Select a player to see their breakdown and override any stat.</div>
        <div id="playerdetailbody" hidden></div>
      </aside>
    </div>
    <section class="blind-note">
      <div class="sec-head"><h2>Where this is blind</h2></div>
      <div class="warn">
        <p><strong>About a third of all ownership</strong> sits on players with no
        EFL record, so the model cannot rate them. They are ex-Premier League
        players at relegated clubs. Trust your own judgement on these until they
        have played a few games.</p>
        <div class="blind" id="blind"></div>
      </div>
    </section>
  </div>

  <!-- ===== Team Projections ===== -->
  <div id="view-clubs" class="view" hidden>
    <div class="toolrow">
      <div class="filters" id="clubfilters" role="group" aria-label="Filter by league"></div>
      <div class="filters" id="clubha" role="group" aria-label="Filter home or away"></div>
      <input class="search" id="clubsearch" type="search" placeholder="Search club&hellip;" aria-label="Search clubs">
    </div>
    <div class="filterbar" id="clubfilterbar"></div>
    <div class="listcount label" id="clubcount"></div>
    <div class="players-body">
      <div class="tablewrap scroller" id="clubtable"></div>
      <aside class="detailcol" id="clubdetail">
        <div class="detail-head"><h2>Team breakdown</h2></div>
        <div class="detail-empty" id="clubdetailempty">Select a club to see its breakdown and reprice it from live odds.</div>
        <div id="clubdetailbody" hidden></div>
      </aside>
    </div>
  </div>

  <!-- ===== Historical Data ===== -->
  <div id="view-history" class="view" hidden>
    <div class="detailcol wide">
      <div class="detail-head"><h2>Historical data</h2></div>
      <div class="detail-empty">
        <p>Load any player&rsquo;s past gameweeks: what the model projected, the
        full breakdown, and how many points they actually scored &mdash; so we can
        track forecasting accuracy per metric and see where the model is strong
        or weak.</p>
        <p>This fills in once real gameweeks have been played and results are
        differenced from the snapshots. Empty by design pre-season.</p>
      </div>
    </div>
  </div>

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
  const CLUB_BY_NAME = new Map((DATA.clubs || []).map((c) => [c.name, c]));
  const clubOf = (r) => CLUB_BY_NAME.get(r.club);
  // A rough 3-letter tag from a club name (drop an AFC prefix, strip spaces).
  const clubAbbr = (name) =>
    (name || "").replace(/^AFC\\s+/i, "").replace(/\\s+/g, "").slice(0, 3).toUpperCase();

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
      (row.div ? " div-" + row.div : "") +
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
    // Difficulty of the first fixture; a double gameweek shows the earlier one.
    const tier = row.fixtures && row.fixtures[0] && row.fixtures[0].tier;
    if (tier) metaRow.append(tierChip(tier));
    metaRow.append(document.createTextNode(meta));
    who.append(metaRow);
    li.append(who);

    const nums = el("div", "nums");
    const xp = el("div", "xp", fmt(pointsFor(row)));
    nums.append(xp);
    // Elite ownership sits beside the overall figure when it has been
    // collected. The gap between them is the point: a player the field
    // ignores and the top managers back is not a differential.
    const ownText = Number.isFinite(row.elite)
      ? row.own.toFixed(1) + "%  elite " + row.elite.toFixed(0) + "%"
      : row.own.toFixed(1) + "% owned";
    const own = el("div", "own", ownText);
    if (Number.isFinite(row.elite) && row.elite - row.own >= 10) {
      own.classList.add("elite-up");
    } else if (Number.isFinite(row.elite) && row.own - row.elite >= 10) {
      own.classList.add("elite-down");
    }
    nums.append(own);
    const statsToggle = el("button", "statstoggle", "STATS");
    statsToggle.type = "button";
    nums.append(statsToggle);
    li.append(nums);

    function refresh() {
      xp.textContent = fmt(pointsFor(row));
      li.classList.toggle("adjusted", isAdjusted(row.id));
      opts.onChange && opts.onChange();
    }

    li.dataset.pid = row.id;
    li.append(minutesControl(row, state, refresh));

    if (opts.onSelect) {
      // Player Projections: the row stays a compact list entry; the full
      // breakdown and stat overrides live in the side panel, opened by
      // clicking the row. One editing surface, not two competing ones.
      statsToggle.textContent = "DETAILS";
      const open = () => opts.onSelect(row);
      statsToggle.addEventListener("click", open);
      who.style.cursor = "pointer";
      who.addEventListener("click", open);
    } else {
      const panel = statsPanel(row, state, refresh);
      panel.hidden = true;
      statsToggle.addEventListener("click", () => {
        panel.hidden = !panel.hidden;
        statsToggle.classList.toggle("on", !panel.hidden);
      });
      li.append(panel);
    }

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
    const li = el("li", "row club-row" + (c.div ? " div-" + c.div : ""));
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

  // The model's recommended squad now seeds the Team Planner tab rather than
  // being shown as its own list -- "Fill from model" drops it onto the pitch.
  // The squad ids are still used above to time the rolling lockout.

  // Full club table, with fixture counts for the coming weeks. Counts only --
  // odds exist for the next round alone, so there is nothing honest to project
  // beyond it.
  // Side panel when the window can fit one; the row-below breakdown otherwise.
  // Defined here because both the club and player tabs use it, and the club
  // tab is built first.
  const wideQuery = window.matchMedia("(min-width: 96rem)");

  // ---- Team Projections table ----------------------------------------
  const clubTableWrap = document.getElementById("clubtable");
  const clubFilters = document.getElementById("clubfilters");
  const clubSearchInput = document.getElementById("clubsearch");
  const clubDetailEmpty = document.getElementById("clubdetailempty");
  const clubDetailBody = document.getElementById("clubdetailbody");
  let clubLeague = "ALL";
  let clubHA = "ALL";
  let clubSearch = "";
  let selectedClubName = null;
  let clubCols = [];
  const clubSortState = { key: "xp", dir: "desc" };
  // Threshold filters: a floor on xPts, ceilings on the win / CS / o1.5 odds
  // (a shorter maximum keeps only the likelier teams).
  const clubThresh = { xpMin: null, winMax: null, csMax: null, o15Max: null };

  // Per-club overrides: each component probability can be replaced by hand
  // (entered as odds), and the projection recomputes from the overridden term.
  const clubOverrides = new Map();  // name -> { win?, draw?, cs?, o15?, o35? }
  const CLUB_COMP_KEYS = ["win", "draw", "cs", "o15", "o35"];
  function clubProb(c, key) {
    const o = clubOverrides.get(c.name);
    return (o && o[key] != null) ? o[key] : c[key];
  }
  function clubIsOver(c, key) {
    const o = clubOverrides.get(c.name);
    return !!(o && o[key] != null);
  }
  function clubAdjusted(c) {
    const o = clubOverrides.get(c.name);
    return !!(o && Object.keys(o).length);
  }
  function clubXp(c) {
    const w = clubProb(c, "win");
    return 5 * w + (c.away ? 2 * w : 0) + 3 * clubProb(c, "draw") +
      2 * clubProb(c, "cs") + 2 * clubProb(c, "o15") + 2 * clubProb(c, "o35");
  }
  function setClubOverride(club, key, p) {
    let o = clubOverrides.get(club.name);
    if (!o) { o = {}; clubOverrides.set(club.name, o); }
    if (p == null) {
      delete o[key];
      if (!Object.keys(o).length) clubOverrides.delete(club.name);
    } else { o[key] = p; }
  }
  function clearClubOverride(club, key) { setClubOverride(club, key, null); }

  function outlookStrip(counts) {
    const strip = el("div", "outlook");
    counts.forEach((n) => {
      strip.append(el("span", "fx" + (n > 1 ? " double" : n ? "" : " blank"),
        n ? String(n) : "\\u00b7"));
    });
    return strip;
  }

  // Card-style club row, still used by the planner's club slots and picker.
  function clubTableRow(c, rank) {
    const li = el("li", "row club-row" + (c.div ? " div-" + c.div : ""));
    li.append(el("div", "pos", String(rank)));
    const who = el("div", "who");
    who.append(el("div", "name", c.name));
    const clubMeta = el("div", "meta");
    if (c.tier) clubMeta.append(tierChip(c.tier));
    clubMeta.append(document.createTextNode(
      c.opp + " (" + (c.away ? "A" : "H") + ")  \\u00b7  CS " + Math.round(c.cs * 100) + "%"));
    who.append(clubMeta);
    if (c.outlook && c.outlook.length) who.append(outlookStrip(c.outlook));
    li.append(who);
    const nums = el("div", "nums");
    nums.append(el("div", "xp", fmt(c.xp)));
    li.append(nums);
    return li;
  }

  // Components read as decimal odds (1 / probability); shorter is likelier.
  const oddsStr = (p) => (p > 0 ? (1 / p).toFixed(2) : "\\u2013");
  const oddsVal = (p) => (p > 0 ? 1 / p : 999);

  // An inline, always-editable odds cell for a club component -- the table
  // twin of the breakdown's price inputs. Editing it overrides the term and
  // recomputes, exactly as on the side panel.
  function clubOddsInput(club, key) {
    const input = document.createElement("input");
    input.type = "number"; input.step = "0.01"; input.min = "1.01";
    input.className = "cellinput";
    input.value = oddsStr(clubProb(club, key));
    input.addEventListener("click", (e) => e.stopPropagation());
    input.addEventListener("change", () => {
      const v = parseFloat(input.value);
      setClubOverride(club, key, (Number.isFinite(v) && v > 1) ? 1 / v : null);
      refreshClubs();
    });
    return input;
  }

  // Team expected goals, recovered from o1.5 = P(2+ goals). For a Poisson
  // scoring rate lambda, P(>=2) = 1 - e^-lambda(1 + lambda), which is
  // monotonic, so a bisection inverts it. Approximate -- a proper xG is a
  // future job -- but it moves correctly with an o1.5 override.
  function teamXg(club) {
    const p = clubProb(club, "o15");
    if (!(p > 0)) return 0;
    let lo = 0.01, hi = 8;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      const f = 1 - poissonPmf(0, mid) - poissonPmf(1, mid);
      if (f < p) lo = mid; else hi = mid;
    }
    return (lo + hi) / 2;
  }

  function clubColumns(rows) {
    // Each component column reads as odds and sorts by odds, but shades by the
    // underlying probability (higher = greener) so shorter odds read stronger.
    // An overridden term drops the green tint for the violet override colour.
    const compShade = {};
    CLUB_COMP_KEYS.forEach((k) => { compShade[k] = shadeFor(rows, (c) => clubProb(c, k), false); });
    const xpShade = shadeFor(rows, (c) => clubXp(c), false);
    const comp = (key, label) => ({
      key, label, align: "right",
      value: (c) => oddsVal(clubProb(c, key)),
      cell: (c) => clubOddsInput(c, key),
      shade: (c) => clubIsOver(c, key) ? null : compShade[key](c),
      cellClass: (c) => clubIsOver(c, key) ? "overridden" : "",
    });
    return [
      { key: "name", label: "Club", numeric: false,
        value: (c) => c.name.toLowerCase(), cell: (c) => el("span", "pname", c.name) },
      { key: "ha", label: "H/A", numeric: false,
        value: (c) => c.away ? "A" : "H", cell: (c) => c.away ? "A" : "H" },
      { key: "div", label: "Lg", numeric: false,
        value: (c) => c.div || "",
        cell: (c) => c.div ? el("span", "divbadge " + c.div, c.div) : "" },
      { key: "opp", label: "Opp", numeric: false,
        value: (c) => (c.opp || "").toLowerCase(), cell: (c) => c.opp || "" },
      { key: "gap", label: "", sortable: false,
        value: () => 0, cell: () => "", cellClass: () => "gapcol" },
      { key: "xp", label: "xPts", align: "right",
        value: (c) => clubAdjusted(c) ? clubXp(c) : c.xp,
        cell: (c) => fmt(clubAdjusted(c) ? clubXp(c) : c.xp),
        shade: (c) => clubAdjusted(c) ? null : xpShade(c),
        cellClass: (c) => clubAdjusted(c) ? "overridden" : "" },
      { key: "xg", label: "xG", align: "right",
        value: (c) => teamXg(c), cell: (c) => teamXg(c).toFixed(2),
        shade: shadeFor(rows, (c) => teamXg(c), false) },
      comp("win", "Win"), comp("draw", "Draw"), comp("cs", "CS"),
      comp("o15", "o1.5"), comp("o35", "o3.5"),
    ];
  }

  // Reprice a single club: enter live win / over-2.5 odds and the ported
  // goal-rate solver recomputes its projection. Fresh controls per click.
  function repriceForm(club) {
    const box = el("div", "odds-box");
    const grid = el("div", "odds-grid");
    const mk = (labelText) => {
      const field = el("div", "odds-field");
      const label = document.createElement("label");
      label.textContent = labelText;
      const input = document.createElement("input");
      input.type = "number"; input.step = "0.01"; input.min = "1.01";
      input.inputMode = "decimal";
      field.append(label, input);
      grid.append(field);
      return input;
    };
    const winIn = mk("Win");
    const overIn = mk("Over 2.5");
    box.append(grid);

    const out = el("div", "odds-out");
    const left = el("div");
    const ptsOut = el("div", "odds-pts", "\\u2013");
    const baseOut = el("div", "odds-note");
    baseOut.style.textAlign = "left";
    left.append(ptsOut, baseOut);
    const impliedOut = el("div", "odds-note");
    out.append(left, impliedOut);
    box.append(out);

    const toOdds = (p) => (p > 0 ? (1 / p).toFixed(2) : "");
    const market = fitRates({ win: club.win, cs: club.cs }, club.away);
    winIn.value = toOdds(club.win);
    overIn.value = toOdds(overTwoFive(market.scored, market.conceded));

    function recalc() {
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
      const fit = fitRates(targets, club.away);
      const r = clubPoints(fit.scored, fit.conceded, club.away);
      ptsOut.textContent = r.points.toFixed(2);
      const shift = r.points - club.xp;
      baseOut.textContent = "market says " + club.xp.toFixed(2) +
        "  (" + (shift >= 0 ? "+" : "") + shift.toFixed(2) + ")";
      const back = [
        targets.win != null ? "win " + toOdds(r.pWin) : null,
        targets.over != null ? "o2.5 " + toOdds(overTwoFive(fit.scored, fit.conceded)) : null,
        "cs " + toOdds(r.cleanSheet),
      ].filter(Boolean).join("  ");
      impliedOut.textContent = fit.scored.toFixed(2) + " scored, " +
        fit.conceded.toFixed(2) + " conceded\\n" + back;
      impliedOut.style.whiteSpace = "pre-line";
    }
    [winIn, overIn].forEach((i) => i.addEventListener("input", recalc));
    recalc();
    return box;
  }

  // One term of the xPts: "label  N x [odds]  =  output", with the odds
  // overridable. Editing it recomputes the term and the total and highlights
  // the club in the table; AUTO reverts to the model's price.
  function compEditLine(club, key, label, mult, onEdit) {
    const relink = onEdit || refreshClubs;
    const line = el("div", "compedit");
    const over = clubIsOver(club, key);
    line.append(el("span", "compedit-lab", label));
    line.append(el("span", "compedit-mult", mult + " \\u00d7"));
    const input = document.createElement("input");
    input.type = "number"; input.step = "0.01"; input.min = "1.01";
    input.className = "oddsinput" + (over ? " overridden-input" : "");
    input.value = oddsStr(clubProb(club, key));
    input.addEventListener("click", (e) => e.stopPropagation());
    input.addEventListener("change", () => {
      const v = parseFloat(input.value);
      setClubOverride(club, key, (Number.isFinite(v) && v > 1) ? 1 / v : null);
      relink();
    });
    line.append(input);
    line.append(el("span", "compedit-eq", "="));
    line.append(el("span", "compedit-out", (mult * clubProb(club, key)).toFixed(2)));
    const reset = el("button", "reset" + (over ? " on" : ""), "AUTO");
    reset.type = "button";
    reset.style.visibility = over ? "visible" : "hidden";
    reset.addEventListener("click", () => { clearClubOverride(club, key); relink(); });
    line.append(reset);
    return line;
  }

  function clubBreakdown(club, onEdit) {
    const relink = onEdit || refreshClubs;
    const wrap = el("div", "breakdown");
    const head = el("div", "detail-player");
    head.append(el("div", "name",
      club.name + " v " + club.opp + " (" + (club.away ? "A" : "H") + ")"));
    head.append(el("div", "meta",
      "xPts " + fmt(clubAdjusted(club) ? clubXp(club) : club.xp) +
      (club.fx > 1 ? "  \\u00b7  " + club.fx + " fixtures" : "")));
    wrap.append(head);

    wrap.append(el("div", "label", "How the xPts is built \\u2014 override any price"));
    const bd = el("div", "compedits");
    bd.append(compEditLine(club, "win", "Win", 5, relink));
    if (club.away) {
      // The away-win bonus rides on the win price, so it is shown but not
      // separately editable.
      const line = el("div", "compedit derived");
      line.append(el("span", "compedit-lab", "Away-win bonus"));
      line.append(el("span", "compedit-mult", "2 \\u00d7"));
      line.append(el("span", "compedit-odds", oddsStr(clubProb(club, "win"))));
      line.append(el("span", "compedit-eq", "="));
      line.append(el("span", "compedit-out", (2 * clubProb(club, "win")).toFixed(2)));
      bd.append(line);
    }
    bd.append(compEditLine(club, "draw", "Draw", 3, relink));
    bd.append(compEditLine(club, "cs", "Clean sheet", 2, relink));
    bd.append(compEditLine(club, "o15", "2+ goals (o1.5)", 2, relink));
    bd.append(compEditLine(club, "o35", "4+ goals (o3.5)", 2, relink));

    const totalLine = el("div", "compedit comptotal");
    totalLine.append(el("span", "compedit-lab", "Total xPts"));
    totalLine.append(el("span", "compedit-out big",
      fmt(clubAdjusted(club) ? clubXp(club) : club.xp)));
    bd.append(totalLine);
    wrap.append(bd);

    if (clubAdjusted(club)) {
      const resetAll = el("button", "chip", "Reset team");
      resetAll.type = "button";
      resetAll.addEventListener("click", () => { clubOverrides.delete(club.name); relink(); });
      wrap.append(resetAll);
    }

    if (club.outlook && club.outlook.length) {
      wrap.append(el("div", "label", "Fixtures over the coming weeks"));
      wrap.append(outlookStrip(club.outlook));
    }
    wrap.append(el("div", "label", "Reprice from live odds"));
    wrap.append(repriceForm(club));
    return wrap;
  }

  function clubMatches() {
    const q = clubSearch.trim().toLowerCase();
    return DATA.clubs.filter((c) => {
      if (clubLeague !== "ALL" && c.div !== clubLeague) return false;
      if (clubHA !== "ALL" && (c.away ? "A" : "H") !== clubHA) return false;
      if (q && !(c.name.toLowerCase().includes(q) ||
                 (c.opp || "").toLowerCase().includes(q))) return false;
      const xp = clubAdjusted(c) ? clubXp(c) : c.xp;
      if (clubThresh.xpMin != null && xp < clubThresh.xpMin) return false;
      if (clubThresh.winMax != null && oddsVal(clubProb(c, "win")) > clubThresh.winMax) return false;
      if (clubThresh.csMax != null && oddsVal(clubProb(c, "cs")) > clubThresh.csMax) return false;
      if (clubThresh.o15Max != null && oddsVal(clubProb(c, "o15")) > clubThresh.o15Max) return false;
      return true;
    });
  }

  function renderClubs() {
    const rows = clubMatches();
    clubCols = clubColumns(rows);
    const total = sortableTable(clubTableWrap, {
      columns: clubCols, rows: rows, sortState: clubSortState,
      keyOf: (c) => c.name,
      rowClass: (c) => clubAdjusted(c) ? "adjusted" : "",
      onRowClick: (c) => {
        selectedClubName = (selectedClubName === c.name) ? null : c.name;
        refreshClubs();
      },
      expandedKey: selectedClubName,
      expand: wideQuery.matches ? null : clubBreakdown,
      rerender: renderClubs,
    });
    document.getElementById("clubcount").textContent =
      total + (clubLeague !== "ALL" || clubSearch
        ? " match" + (total === 1 ? "" : "es") : " clubs");
  }

  function renderClubDetail() {
    const club = selectedClubName ? DATA.clubs.find((c) => c.name === selectedClubName) : null;
    const show = wideQuery.matches && club;
    clubDetailEmpty.hidden = !!show;
    clubDetailBody.hidden = !show;
    clubDetailBody.replaceChildren();
    if (show) clubDetailBody.append(clubBreakdown(club));
  }

  function refreshClubs() { renderClubs(); renderClubDetail(); }
  wideQuery.addEventListener("change", refreshClubs);

  // League filter.
  [["ALL", "All"], ["CH", "Champ"], ["L1", "League 1"], ["L2", "League 2"]]
    .forEach(([code, label]) => {
      const b = el("button", "chip", label);
      b.type = "button";
      b.dataset.lg = code;
      b.setAttribute("aria-pressed", String(code === clubLeague));
      b.addEventListener("click", () => {
        clubLeague = code;
        clubFilters.querySelectorAll(".chip").forEach((x) =>
          x.setAttribute("aria-pressed", String(x.dataset.lg === code)));
        refreshClubs();
      });
      clubFilters.append(b);
    });

  // Home / away filter.
  const clubHAbar = document.getElementById("clubha");
  [["ALL", "H & A"], ["H", "Home"], ["A", "Away"]].forEach(([code, label]) => {
    const b = el("button", "chip", label);
    b.type = "button";
    b.dataset.ha = code;
    b.setAttribute("aria-pressed", String(code === clubHA));
    b.addEventListener("click", () => {
      clubHA = code;
      clubHAbar.querySelectorAll(".chip").forEach((x) =>
        x.setAttribute("aria-pressed", String(x.dataset.ha === code)));
      refreshClubs();
    });
    clubHAbar.append(b);
  });

  // Threshold filters: xPts floor, and odds ceilings on win / CS / o1.5.
  const clubBar = document.getElementById("clubfilterbar");
  const addClubNum = (labelText, key, step) => {
    const item = el("div", "fitem");
    item.append(document.createTextNode(labelText));
    const input = document.createElement("input");
    input.type = "number"; input.step = step; input.min = "0";
    input.addEventListener("input", () => {
      const v = parseFloat(input.value);
      clubThresh[key] = Number.isFinite(v) ? v : null;
      renderClubs();
    });
    item.append(input);
    clubBar.append(item);
  };
  addClubNum("xPts \\u2265", "xpMin", "0.1");
  addClubNum("Win \\u2264", "winMax", "0.05");
  addClubNum("CS \\u2264", "csMax", "0.05");
  addClubNum("o1.5 \\u2264", "o15Max", "0.05");

  clubSearchInput.addEventListener("input", () => {
    clubSearch = clubSearchInput.value;
    renderClubs();
  });

  refreshClubs();

  // Full player pool: every selectable player, not just a top 20, with a
  // position filter, free-text search and a sort choice. Capped at
  // POOL_SHOWN per filter/search combination with a "show all" button --
  // the same disclosure pattern as the club table above -- so the initial
  // render stays light even for a 600-player division on a phone.
  const filters = document.getElementById("filters");
  const poolSearchInput = document.getElementById("poolsearch");
  const poolTableWrap = document.getElementById("pooltable");
  const detailEmpty = document.getElementById("playerdetailempty");
  const detailBody = document.getElementById("playerdetailbody");

  let active = "MID";
  let poolSearch = "";
  let poolClubs = new Set();        // empty means every club
  let overriddenOnly = false;
  let selectedPlayerId = null;
  let poolCols = [];                // the live column set, for targeted repaints
  const poolSortState = { key: "xp", dir: "desc" };
  // Threshold filters: a min for most, a max for goals conceded, both for own%.
  const poolThresholds = { xp: null, ownMin: null, ownMax: null, stats: {} };

  // Value shading: tint a stat cell in proportion to its value within the
  // shown pool -- the column's min maps to bare, its max to full, so the
  // shade tracks the number itself (3.31 always reads at least as strong as
  // 3.30). One hue varying only in intensity, which stays legible under any
  // colour-vision deficiency -- a red/green ramp would not.
  function shadeBg(p) {
    if (p == null) return "";
    return "rgba(78, 158, 95, " + (0.08 + 0.5 * p).toFixed(3) + ")";
  }
  function computeShades(rows, getVal, invert) {
    let min = Infinity, max = -Infinity;
    rows.forEach((r) => {
      const v = getVal(r);
      if (!Number.isFinite(v)) return;
      if (v < min) min = v;
      if (v > max) max = v;
    });
    const span = max - min;
    // Keyed by the row object itself, not an id -- clubs have no id, which
    // silently collapsed every club to a single shade.
    const map = new Map();
    rows.forEach((r) => {
      const v = getVal(r);
      if (!Number.isFinite(v) || span <= 0) { map.set(r, null); return; }
      const p = (v - min) / span;
      map.set(r, invert ? 1 - p : p);
    });
    return map;
  }
  function shadeFor(rows, getVal, invert) {
    const map = computeShades(rows, getVal, invert);
    return (row) => map.get(row);
  }

  // ---- Reusable sortable, expandable data table -----------------------
  // Backs Player Projections, Team Projections and the planner picker.
  // columns: [{ key, label, value(row), cell(row)->string|node, align,
  //             numeric, sortable }]. A header click sorts by that column,
  //             toggling desc/asc; a row click runs onRowClick(row, tr).
  // Returns the row count after filtering so the caller can drive a count
  // and a "show all" button.
  function sortableTable(container, opts) {
    const { columns, rows, sortState, keyOf, rowClass,
            onRowClick, expandedKey, expand, limit } = opts;
    const table = el("table", "dtable");

    const thead = el("thead");
    const htr = el("tr");
    columns.forEach((col) => {
      const th = el("th", col.align === "right" ? "num" : "");
      th.append(document.createTextNode(col.label));
      if (col.title) th.title = col.title;
      if (col.sortable !== false) {
        th.classList.add("sortable");
        if (sortState.key === col.key) {
          th.classList.add("sorted");
          th.append(el("span", "arrow", sortState.dir === "asc" ? " \\u25b2" : " \\u25bc"));
        }
        th.addEventListener("click", () => {
          if (sortState.key === col.key) {
            sortState.dir = sortState.dir === "desc" ? "asc" : "desc";
          } else {
            sortState.key = col.key;
            sortState.dir = col.numeric === false ? "asc" : "desc";
          }
          opts.rerender();
        });
      }
      htr.append(th);
    });
    thead.append(htr);
    table.append(thead);

    const sortCol = columns.find((c) => c.key === sortState.key) || columns[0];
    const dir = sortState.dir === "asc" ? 1 : -1;
    const sorted = rows.slice().sort((a, b) => {
      const va = sortCol.value(a), vb = sortCol.value(b);
      if (typeof va === "string" || typeof vb === "string") {
        return dir * String(va).localeCompare(String(vb));
      }
      return dir * (va - vb);
    });
    const visible = limit ? sorted.slice(0, limit) : sorted;

    const tbody = el("tbody");
    visible.forEach((row) => {
      const tr = el("tr", rowClass ? rowClass(row) : "");
      const rk = keyOf ? String(keyOf(row)) : null;
      if (rk != null) tr.dataset.rk = rk;
      columns.forEach((c) => {
        const td = el("td", c.align === "right" ? "num" : "");
        td.dataset.col = c.key;
        if (c.cellClass) { const cc = c.cellClass(row); if (cc) td.className += " " + cc; }
        const content = c.cell(row);
        if (content == null) { /* blank cell */ }
        else if (typeof content === "string") td.append(document.createTextNode(content));
        else td.append(content);
        if (c.shade) { const s = c.shade(row); if (s != null) td.style.background = shadeBg(s); }
        tr.append(td);
      });
      if (onRowClick) {
        tr.classList.add("clickable");
        tr.addEventListener("click", (e) => {
          if (e.target.closest("button, input, select, a, label")) return;
          onRowClick(row, tr);
        });
      }
      if (expandedKey != null && rk === String(expandedKey)) tr.classList.add("selected-row");
      tbody.append(tr);

      if (expand && expandedKey != null && rk === String(expandedKey)) {
        const extr = el("tr", "expand");
        const td = el("td");
        td.colSpan = columns.length;
        td.append(expand(row));
        extr.append(td);
        tbody.append(extr);
      }
    });
    table.append(tbody);
    container.replaceChildren(table);
    return sorted.length;
  }

  // ---- Player Projections table --------------------------------------
  // Stat columns shown depend on the position on screen -- a keeper has no
  // tackles column, a midfielder no clean-sheet column.
  const STAT_COLS = [
    { key: "goals", label: "xG", pos: ["DEF", "MID", "FWD"] },
    { key: "assists", label: "xA", pos: ["DEF", "MID", "FWD"] },
    { key: "shotsOnTarget", label: "SoT", pos: ["MID", "FWD"] },
    { key: "keyPasses", label: "KP", pos: ["MID", "FWD"] },
    { key: "interceptions", label: "Int", pos: ["MID"] },
    { key: "tackles", label: "Tkl", pos: ["DEF"] },
    { key: "clearances", label: "Clr", pos: ["DEF"] },
    { key: "blocks", label: "Blk", pos: ["DEF"] },
    { key: "saves", label: "Sv", pos: ["GK"] },
    { key: "pCleanSheet", label: "CS%", pos: ["GK", "DEF"], percent: true },
    { key: "goalsConceded", label: "GC", pos: ["GK", "DEF"] },
  ];

  function effFixtures(row) { return effectiveFixtures(row, stateFor(row.id)); }
  function statAgg(row, key) { return effFixtures(row).reduce((s, f) => s + (f[key] || 0), 0); }
  function statPct(row, key) { const f = effFixtures(row)[0]; return f ? (f[key] || 0) : 0; }
  function oppText(row) {
    if (!row.fixtures.length) return "-";
    return row.fixtures.map((f) => f.opp + " (" + (f.away ? "A" : "H") + ")").join(", ");
  }

  // Every stat is read and edited as a per-fixture rate (statPct already
  // returns fixtures[0][key]); a double gameweek applies the same rate to
  // both matches, exactly as the side-panel override does.
  const fieldOver = (row, key) =>
    Object.prototype.hasOwnProperty.call(stateFor(row.id).fields, key);
  const minsOver = (row) => stateFor(row.id).xmins !== POOL_BY_ID.get(row.id).xmins;

  // An always-editable numeric cell: commit on change, then repaint the row
  // (and the side panel, if this player is open) so the table, the panel and
  // the override highlight never disagree.
  function statInput(row, col) {
    const input = document.createElement("input");
    input.type = "number";
    input.className = "cellinput";
    input.step = col.percent ? "1" : "0.01";
    input.min = "0";
    input.value = col.inputVal(row);
    input.addEventListener("click", (e) => e.stopPropagation());
    input.addEventListener("change", () => {
      let v = parseFloat(input.value);
      if (!Number.isFinite(v) || v < 0) v = 0;
      col.commit(row, v);
      refreshAll();
    });
    return input;
  }

  function poolColumns(rows) {
    const cols = [
      { key: "name", label: "Player", numeric: false,
        value: (r) => r.name.toLowerCase(), cell: (r) => el("span", "pname", r.name) },
      { key: "club", label: "Team", numeric: false,
        value: (r) => r.club.toLowerCase(), cell: (r) => r.club },
    ];
    // With every position on screen, position is a column; with one position
    // filtered it is redundant and the space goes to the stat columns.
    if (active === "ALL") {
      cols.push({ key: "pos", label: "Pos", numeric: false,
        value: (r) => r.pos, cell: (r) => r.pos });
    }
    cols.push({ key: "opp", label: "Opp", numeric: false,
      value: (r) => oppText(r).toLowerCase(), cell: (r) => oppText(r) });

    // Spacer: divides the identity columns from the figures and pushes the
    // table out to the divide so its scrollbar sits at the screen's middle.
    cols.push({ key: "gap", label: "", sortable: false,
      value: () => 0, cell: () => "", cellClass: () => "gapcol" });

    cols.push({
      key: "xp", label: "xPts", align: "right",
      value: (r) => pointsFor(r), cell: (r) => fmt(pointsFor(r)),
      shade: shadeFor(rows, (r) => pointsFor(r), false),
      refresh: (td, r) => { td.textContent = fmt(pointsFor(r)); },
    });

    const minsShade = shadeFor(rows, (r) => stateFor(r.id).xmins, false);
    cols.push({
      key: "xmins", label: "xMins", align: "right", percent: false,
      value: (r) => stateFor(r.id).xmins,
      inputVal: (r) => String(stateFor(r.id).xmins),
      commit: (r, v) => { stateFor(r.id).xmins = Math.max(0, Math.min(90, Math.round(v))); },
      shade: (r) => minsOver(r) ? null : minsShade(r),
      cellClass: (r) => minsOver(r) ? "overridden" : "",
      refresh: (td, r) => paintEditable(td, r, "xmins"),
    });

    cols.push({ key: "own", label: "Own%", align: "right",
      value: (r) => r.own, cell: (r) => r.own.toFixed(1) });

    // Position-specific scoring metrics only when a single position is shown.
    if (active !== "ALL") {
      STAT_COLS.filter((s) => s.pos.includes(active)).forEach((s) => {
        const shade = shadeFor(rows, (r) => statPct(r, s.key), s.key === "goalsConceded");
        cols.push({
          key: s.key, label: s.label, align: "right", percent: !!s.percent,
          value: (r) => statPct(r, s.key),
          inputVal: (r) => s.percent
            ? String(Math.round(statPct(r, s.key) * 100))
            : statPct(r, s.key).toFixed(2),
          commit: (r, v) => { stateFor(r.id).fields[s.key] = s.percent ? v / 100 : v; },
          shade: (r) => fieldOver(r, s.key) ? null : shade(r),
          cellClass: (r) => fieldOver(r, s.key) ? "overridden" : "",
          refresh: (td, r) => paintEditable(td, r, s.key),
        });
      });
    }

    // Editable columns declare inputVal/commit; wire their cell renderer now
    // that each column object exists for statInput to read off.
    cols.forEach((c) => { if (c.inputVal && c.commit) c.cell = (r) => statInput(r, c); });
    return cols;
  }

  // Repaint one editable cell in place (value, override highlight, shade) so
  // dragging the side-panel minutes slider never rebuilds the whole table.
  function paintEditable(td, row, key) {
    const col = poolCols.find((c) => c.key === key);
    if (!col) return;
    const input = td.querySelector("input");
    if (input) input.value = col.inputVal(row);
    const over = col.cellClass && col.cellClass(row) === "overridden";
    td.classList.toggle("overridden", !!over);
    const s = col.shade ? col.shade(row) : null;
    td.style.background = s == null ? "" : shadeBg(s);
  }

  function paintRow(row) {
    const tr = poolTableWrap.querySelector('tr[data-rk="' + row.id + '"]');
    if (!tr) return;
    poolCols.forEach((c) => {
      if (!c.refresh) return;
      const td = tr.querySelector('td[data-col="' + c.key + '"]');
      if (td) c.refresh(td, row);
    });
    tr.classList.toggle("adjusted", isAdjusted(row.id));
  }

  // ---- Player breakdown, expanded in a row below the player ----------
  function poolExpansion(row, onEdit) {
    const state = stateFor(row.id);
    const wrap = el("div", "breakdown");

    const head = el("div", "detail-player");
    head.append(el("div", "name", row.name));
    head.append(el("div", "meta",
      row.pos + "  \\u00b7  " + row.club + "  \\u00b7  " + oppText(row) +
      "  \\u00b7  " + row.own.toFixed(1) + "% owned"));
    wrap.append(head);

    const summary = el("div", "summary");
    const box = el("div");
    const totalNum = el("div", "total", fmt(pointsFor(row)));
    box.append(totalNum);
    box.append(el("div", "total-note", "projected points"));
    summary.append(box);
    wrap.append(summary);

    if (row.fixtures.length > 1) {
      wrap.append(el("div", "label",
        "Per fixture: " + row.fixtures.map((f) => f.opp + " " + fmt(f.xp)).join("   ")));
    }

    // Edits repaint the matching table row, and notify any other view (the
    // planner) so every place this player appears stays identical.
    const refresh = () => {
      totalNum.textContent = fmt(pointsFor(row));
      paintRow(row);
      if (onEdit) onEdit();
    };

    wrap.append(el("div", "label", "Expected minutes"));
    wrap.append(minutesControl(row, state, refresh));
    wrap.append(el("div", "label", "Override any stat"));
    wrap.append(statsPanel(row, state, refresh));
    return wrap;
  }

  // Threshold inputs, rebuilt per position so the stat filters match the
  // columns on screen. A min for everything bar goals conceded (a max) and
  // own% (both); expected minutes gets none.
  function renderFilterBar() {
    const bar = document.getElementById("poolfilters");
    bar.replaceChildren();
    const addNum = (labelText, get, set, step) => {
      const item = el("div", "fitem");
      item.append(document.createTextNode(labelText));
      const input = document.createElement("input");
      input.type = "number";
      input.step = step || "0.1";
      input.min = "0";
      const cur = get();
      input.value = cur == null ? "" : String(cur);
      input.addEventListener("input", () => {
        const v = parseFloat(input.value);
        set(Number.isFinite(v) ? v : null);
        renderPool();
      });
      item.append(input);
      bar.append(item);
    };
    addNum("xPts \\u2265", () => poolThresholds.xp, (v) => { poolThresholds.xp = v; });
    addNum("Own% \\u2265", () => poolThresholds.ownMin, (v) => { poolThresholds.ownMin = v; }, "1");
    addNum("Own% \\u2264", () => poolThresholds.ownMax, (v) => { poolThresholds.ownMax = v; }, "1");
    if (active !== "ALL") {
      STAT_COLS.filter((s) => s.pos.includes(active)).forEach((s) => {
        const isMax = s.key === "goalsConceded";
        addNum(s.label + (isMax ? " \\u2264" : " \\u2265"),
          () => poolThresholds.stats[s.key],
          (v) => { poolThresholds.stats[s.key] = v; },
          s.percent ? "1" : "0.1");
      });
    }
  }

  function poolMatches() {
    const q = poolSearch.trim().toLowerCase();
    return DATA.pool.filter((row) => {
      if (active !== "ALL" && row.pos !== active) return false;
      if (poolClubs.size && !poolClubs.has(row.club)) return false;
      if (overriddenOnly && !isAdjusted(row.id)) return false;
      if (q && !(row.name.toLowerCase().includes(q) ||
                 row.club.toLowerCase().includes(q))) return false;
      if (poolThresholds.xp != null && pointsFor(row) < poolThresholds.xp) return false;
      if (poolThresholds.ownMin != null && row.own < poolThresholds.ownMin) return false;
      if (poolThresholds.ownMax != null && row.own > poolThresholds.ownMax) return false;
      if (active !== "ALL") {
        for (const s of STAT_COLS) {
          if (!s.pos.includes(active)) continue;
          const t = poolThresholds.stats[s.key];
          if (t == null) continue;
          let val = statPct(row, s.key);
          if (s.percent) val *= 100;
          // Goals conceded is a ceiling; every other stat is a floor.
          if (s.key === "goalsConceded") { if (val > t) return false; }
          else if (val < t) return false;
        }
      }
      return true;
    });
  }

  function renderPool() {
    const rows = poolMatches();
    poolCols = poolColumns(rows);
    const total = sortableTable(poolTableWrap, {
      columns: poolCols,
      rows: rows,
      sortState: poolSortState,
      keyOf: (r) => r.id,
      rowClass: (r) => (r.proven ? "" : "unproven") + (isAdjusted(r.id) ? " adjusted" : ""),
      onRowClick: (r) => {
        selectedPlayerId = (selectedPlayerId === r.id) ? null : r.id;
        refreshAll();
      },
      expandedKey: selectedPlayerId,
      // Inline breakdown only when there is no side panel (narrow screen).
      expand: wideQuery.matches ? null : poolExpansion,
      rerender: renderPool,
    });
    document.getElementById("poolcount").textContent =
      total + (poolSearch || poolClubs.size || overriddenOnly
        ? " match" + (total === 1 ? "" : "es") : " players");
  }

  // Fill the side panel with the selected player's breakdown, when the panel
  // is showing (wide screen); the narrow layout uses the row-below expansion.
  function renderBreakdown() {
    const row = selectedPlayerId != null ? POOL_BY_ID.get(selectedPlayerId) : null;
    const show = wideQuery.matches && row;
    detailEmpty.hidden = !!show;
    detailBody.hidden = !show;
    detailBody.replaceChildren();
    if (show) detailBody.append(poolExpansion(row));
  }

  function refreshAll() { renderPool(); renderBreakdown(); }
  wideQuery.addEventListener("change", refreshAll);

  // Position filter, with an All that drops the position-specific columns.
  [["ALL", "All"], ["GK", "GK"], ["DEF", "DEF"], ["MID", "MID"], ["FWD", "FWD"]]
    .forEach(([code, label]) => {
      const b = el("button", "chip", label);
      b.type = "button";
      b.dataset.pos = code;
      b.setAttribute("aria-pressed", String(code === active));
      b.addEventListener("click", () => {
        active = code;
        filters.querySelectorAll(".chip").forEach((c) =>
          c.setAttribute("aria-pressed", String(c.dataset.pos === code)));
        renderFilterBar();
        renderPool();
      });
      filters.append(b);
    });

  // Club multi-select: tick any number of clubs; none ticked means all.
  const clubBtn = document.getElementById("poolclubbtn");
  const clubPanel = document.getElementById("poolclubpanel");
  const clubNames = Array.from(new Set(DATA.pool.map((r) => r.club))).sort();

  function updateClubBtn() {
    clubBtn.textContent = poolClubs.size === 0
      ? "All clubs"
      : poolClubs.size + " club" + (poolClubs.size === 1 ? "" : "s");
  }
  function buildClubPanel() {
    clubPanel.replaceChildren();
    const allLabel = document.createElement("label");
    const allBox = document.createElement("input");
    allBox.type = "checkbox";
    allBox.checked = poolClubs.size === 0;
    allBox.addEventListener("change", () => {
      poolClubs.clear();
      buildClubPanel();
      updateClubBtn();
      renderPool();
    });
    allLabel.append(allBox, document.createTextNode("All clubs"));
    clubPanel.append(allLabel);
    clubPanel.append(el("div", "msdiv"));
    clubNames.forEach((name) => {
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = poolClubs.has(name);
      box.addEventListener("change", () => {
        if (box.checked) poolClubs.add(name); else poolClubs.delete(name);
        const allInput = clubPanel.querySelector("label input");
        if (allInput) allInput.checked = poolClubs.size === 0;
        updateClubBtn();
        renderPool();
      });
      label.append(box, document.createTextNode(name));
      clubPanel.append(label);
    });
  }
  clubBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    clubPanel.hidden = !clubPanel.hidden;
    clubBtn.setAttribute("aria-expanded", String(!clubPanel.hidden));
  });
  document.addEventListener("click", (e) => {
    if (!clubPanel.hidden && e.target.closest && !e.target.closest(".multiselect")) {
      clubPanel.hidden = true;
    }
  });
  buildClubPanel();
  updateClubBtn();

  // Show only overridden players, and reset every override.
  const overBtn = document.getElementById("pooloverbtn");
  overBtn.addEventListener("click", () => {
    overriddenOnly = !overriddenOnly;
    overBtn.setAttribute("aria-pressed", String(overriddenOnly));
    renderPool();
  });
  document.getElementById("poolresetbtn").addEventListener("click", () => {
    overrides.clear();
    selectedPlayerId = null;
    refreshAll();
  });

  poolSearchInput.addEventListener("input", () => {
    poolSearch = poolSearchInput.value;
    renderPool();
  });

  renderFilterBar();
  refreshAll();

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

  // The repricing UI itself lives in the Team Projections breakdown
  // (repriceForm), built per club when one is selected. The maths above are
  // shared by it.

  // ---- Planner ----------------------------------------------------------
  //
  // Build a squad by hand and watch the total move. Reuses pointsFor, so a
  // player overridden on the projections view carries the same number here.
  // Two totals disagreeing about the same player would be worse than having
  // no planner at all.

  // The only legal shapes: seven players, one keeper, and the game's own
  // bounds of two or three at the back and in midfield.
  const FORMATIONS = {
    "1-2-2-2": { GK: 1, DEF: 2, MID: 2, FWD: 2 },
    "1-2-3-1": { GK: 1, DEF: 2, MID: 3, FWD: 1 },
    "1-3-2-1": { GK: 1, DEF: 3, MID: 2, FWD: 1 },
  };
  const MAX_PER_CLUB = 2;
  const SLOT_ORDER = ["GK", "DEF", "MID", "FWD"];

  const plan = { formation: "1-2-3-1", picks: [], clubs: [], captain: null };

  function clubCount(name, ignoreIndex) {
    return plan.picks.filter((id, i) => {
      if (!id || i === ignoreIndex) return false;
      const row = POOL_BY_ID.get(id);
      return row && row.club === name;
    }).length;
  }

  // The first empty slot a player fits, for browse-mode picking where no
  // specific slot was clicked.
  function firstOpenSlot(row) {
    const positions = slotPositions();
    return positions.findIndex((pos, i) => pos === row.pos && !plan.picks[i]);
  }

  function planIssues() {
    const issues = [];
    const counts = {};
    plan.picks.forEach((id) => {
      if (!id) return;
      const row = POOL_BY_ID.get(id);
      if (row) counts[row.club] = (counts[row.club] || 0) + 1;
    });
    Object.keys(counts).forEach((club) => {
      if (counts[club] > MAX_PER_CLUB) {
        issues.push(counts[club] + " players from " + club + ", limit is " + MAX_PER_CLUB);
      }
    });
    const chosen = plan.clubs.filter(Boolean);
    if (new Set(chosen).size < chosen.length) issues.push("same club picked twice");
    return issues;
  }

  function planPoints() {
    let total = 0;
    plan.picks.forEach((id) => {
      const row = id && POOL_BY_ID.get(id);
      if (row) total += pointsFor(row);
    });
    if (plan.captain && plan.picks.indexOf(plan.captain) !== -1) {
      const cap = POOL_BY_ID.get(plan.captain);
      if (cap) total += pointsFor(cap);
    }
    plan.clubs.forEach((name) => {
      const club = name && DATA.clubs.find((c) => c.name === name);
      if (club) total += (clubAdjusted(club) ? clubXp(club) : club.xp);
    });
    return total;
  }

  function slotPositions() {
    const shape = FORMATIONS[plan.formation];
    const out = [];
    SLOT_ORDER.forEach((pos) => {
      for (let i = 0; i < shape[pos]; i++) out.push(pos);
    });
    return out;
  }

  function updatePlanTotals() {
    const positions = slotPositions();
    const picked = plan.picks.filter(Boolean).length;
    document.getElementById("plantotal").textContent = fmt(planPoints());
    document.getElementById("plannote").textContent =
      picked + " of " + positions.length + " picked" +
      (plan.captain ? ", captain doubled" : ", no captain yet");
    document.getElementById("planwarn").textContent = planIssues().join("   ");
  }

  // ---- The pitch (left) ----------------------------------------------
  const pitchEl = document.getElementById("pitchlines");

  // Club home-kit colours { p: shirt, t: collar/trim }. Pre-filled from real
  // kits so every shirt reads as its club; correct any that look wrong.
  const CLUB_KIT = {
    "Middlesbrough": { p: "#d1122b", t: "#ffffff" },
    "Wolverhampton Wanderers": { p: "#fdb913", t: "#231f20" },
    "Leicester City": { p: "#0053a0", t: "#ffffff" },
    "Southampton": { p: "#d71920", t: "#ffffff" },
    "Bradford City": { p: "#7a2531", t: "#ffc20e" },
    "Huddersfield Town": { p: "#0e63ad", t: "#ffffff" },
    "West Ham United": { p: "#7a263a", t: "#2dafe5" },
    "Grimsby Town": { p: "#000000", t: "#ffffff" },
    "Sheffield Wednesday": { p: "#1b4f9c", t: "#ffffff" },
    "Rochdale": { p: "#0a4ea2", t: "#ffffff" },
    "Luton Town": { p: "#12224a", t: "#ff5000" },
    "Walsall": { p: "#d2122e", t: "#ffffff" },
    "Norwich City": { p: "#fff200", t: "#00a650" },
    "Barnsley": { p: "#e01e26", t: "#ffffff" },
    "Derby County": { p: "#ffffff", t: "#111111" },
    "Wycombe Wanderers": { p: "#0a1f5c", t: "#6c9fd6" },
    "Rotherham United": { p: "#d3122a", t: "#ffffff" },
    "Salford City": { p: "#e21e26", t: "#ffffff" },
    "Shrewsbury Town": { p: "#0a4d9c", t: "#f5a800" },
    "Port Vale": { p: "#ffffff", t: "#111111" },
    "Fleetwood Town": { p: "#d81e05", t: "#ffffff" },
    "Bolton Wanderers": { p: "#ffffff", t: "#12245c" },
    "Northampton Town": { p: "#6f263d", t: "#ffffff" },
    "Crewe Alexandra": { p: "#e1231b", t: "#ffffff" },
    "York City": { p: "#c8102e", t: "#12224a" },
    "Millwall": { p: "#002c5f", t: "#ffffff" },
    "Oxford United": { p: "#ffd200", t: "#12224a" },
    "Mansfield Town": { p: "#f8b400", t: "#12245c" },
    "Colchester United": { p: "#1c449b", t: "#ffffff" },
    "Burton Albion": { p: "#ffdd00", t: "#111111" },
    "Birmingham City": { p: "#0000a8", t: "#ffffff" },
    "Portsmouth": { p: "#001489", t: "#ffffff" },
    "Wrexham": { p: "#d40000", t: "#ffffff" },
    "Swansea City": { p: "#ffffff", t: "#111111" },
    "Plymouth Argyle": { p: "#007b5f", t: "#ffffff" },
    "Stevenage": { p: "#e1231b", t: "#ffffff" },
    "Cambridge United": { p: "#f9a01b", t: "#111111" },
    "Cardiff City": { p: "#0070b5", t: "#ffffff" },
    "Wigan Athletic": { p: "#1d59af", t: "#ffffff" },
    "Reading": { p: "#004494", t: "#ffffff" },
    "Stoke City": { p: "#e03a3e", t: "#ffffff" },
    "Stockport County": { p: "#005ca9", t: "#ffffff" },
    "Queens Park Rangers": { p: "#005cab", t: "#ffffff" },
    "Sheffield United": { p: "#ec2227", t: "#111111" },
    "Bristol City": { p: "#e21c38", t: "#ffffff" },
    "Accrington Stanley": { p: "#d0112b", t: "#ffffff" },
    "Doncaster Rovers": { p: "#d31c2b", t: "#ffffff" },
    "MK Dons": { p: "#ffffff", t: "#111111" },
    "Crawley Town": { p: "#d5122c", t: "#ffffff" },
    "AFC Wimbledon": { p: "#003da5", t: "#ffd200" },
    "Charlton Athletic": { p: "#d50000", t: "#ffffff" },
    "Oldham Athletic": { p: "#004a99", t: "#ffffff" },
    "Chesterfield": { p: "#1d5cb4", t: "#ffffff" },
    "Tranmere Rovers": { p: "#ffffff", t: "#0055a4" },
    "Bristol Rovers": { p: "#003a70", t: "#ffffff" },
    "Cheltenham Town": { p: "#cf0a2c", t: "#ffffff" },
    "Barnet": { p: "#f5a800", t: "#111111" },
    "Blackpool": { p: "#f68712", t: "#ffffff" },
    "Swindon Town": { p: "#d81e28", t: "#ffffff" },
    "Preston North End": { p: "#ffffff", t: "#12224a" },
    "Gillingham": { p: "#005daa", t: "#111111" },
    "Burnley": { p: "#6a003a", t: "#6cabdd" },
    "Bromley": { p: "#ffffff", t: "#111111" },
    "Leyton Orient": { p: "#d50032", t: "#ffffff" },
    "Newport County": { p: "#f7b500", t: "#111111" },
    "West Bromwich Albion": { p: "#122f67", t: "#ffffff" },
    "Exeter City": { p: "#d0021b", t: "#ffffff" },
    "Watford": { p: "#fbee23", t: "#111111" },
    "Notts County": { p: "#000000", t: "#ffffff" },
    "Peterborough United": { p: "#003da5", t: "#ffffff" },
    "Blackburn Rovers": { p: "#005da3", t: "#ffffff" },
    "Lincoln City": { p: "#d81f34", t: "#ffffff" },
  };
  const kitColours = (name) => CLUB_KIT[name] || { p: "#6b7280", t: "#9ca3af" };
  // Dark ink on a light shirt, white on a dark one, so the name stays legible.
  const kitInk = (hex) => {
    const h = hex.replace("#", "");
    const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? "#0a1230" : "#ffffff";
  };
  const shortClub = (name) => name.split(/\\s+/)[0];

  // A jersey in the club's colour with the xPts printed on it (in a legible
  // ink for that colour). The player/club name is drawn by the caller below.
  function kitEl(clubName, overlay) {
    const wrap = el("div", "kit-wrap");
    const kit = el("div", "kit");
    const col = kitColours(clubName);
    kit.style.background = col.p;
    const trim = el("div", "kit-trim");
    trim.style.background = col.t;
    kit.append(trim);
    wrap.append(kit);
    if (overlay != null) {
      const o = el("div", "kit-pts", overlay);
      o.style.color = kitInk(col.p);
      wrap.append(o);
    }
    return wrap;
  }

  function shirt(row, index) {
    const card = el("div", "shirt" +
      (isAdjusted(row.id) ? " adjusted" : "") +
      (row.id === plan.captain ? " captained" : ""));
    card.append(kitEl(row.club, fmt(pointsFor(row))));
    card.append(el("div", "shirt-name", row.name));
    const oppClub = clubOf(row);
    if (oppClub) card.append(el("div", "shirt-opp",
      clubAbbr(oppClub.opp) + " (" + (oppClub.away ? "A" : "H") + ")"));
    const sub = el("div", "shirt-sub");
    const minsIn = el("input", "mins-in" + (minsOver(row) ? " edited" : ""));
    minsIn.type = "number"; minsIn.min = "0"; minsIn.max = "90";
    minsIn.value = String(stateFor(row.id).xmins);
    minsIn.title = "Expected minutes";
    minsIn.addEventListener("click", (e) => e.stopPropagation());
    minsIn.addEventListener("change", () => {
      const v = Math.max(0, Math.min(90, Math.round(parseFloat(minsIn.value) || 0)));
      stateFor(row.id).xmins = v;
      renderPlanner();
    });
    sub.append(minsIn, document.createTextNode(" \\u00b7 " + row.pos));
    card.append(sub);
    const ctl = el("div", "shirt-ctl");
    const capBtn = el("button", "sbtn cap-btn" + (row.id === plan.captain ? " on" : ""), "C");
    capBtn.type = "button"; capBtn.title = "Captain";
    capBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      plan.captain = (plan.captain === row.id) ? null : row.id;
      renderPitch();
    });
    const remBtn = el("button", "sbtn", "\\u2212");
    remBtn.type = "button"; remBtn.title = "Remove";
    remBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      plan.picks[index] = null;
      if (plan.captain === row.id) plan.captain = null;
      renderPlanner();
    });
    ctl.append(capBtn, remBtn);
    card.append(ctl);
    card.addEventListener("click", () => openPlayerModal(row, index));
    return card;
  }

  function clubBadge(club, index) {
    const card = el("div", "shirt club-shirt" + (clubAdjusted(club) ? " adjusted" : ""));
    card.append(kitEl(club.name, fmt(clubAdjusted(club) ? clubXp(club) : club.xp)));
    card.append(el("div", "shirt-name", shortClub(club.name)));
    card.append(el("div", "shirt-opp",
      clubAbbr(club.opp) + " (" + (club.away ? "A" : "H") + ")"));
    const ctl = el("div", "shirt-ctl");
    const remBtn = el("button", "sbtn", "\\u2212");
    remBtn.type = "button"; remBtn.title = "Remove";
    remBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      plan.clubs[index] = null;
      renderPlanner();
    });
    ctl.append(remBtn);
    card.append(ctl);
    card.addEventListener("click", () => openClubModal(club));
    return card;
  }

  function emptyShirt(label, index, isClub) {
    const card = el("button", "shirt empty");
    card.type = "button";
    const wrap = el("div", "kit-wrap");
    wrap.append(el("div", "kit ghost"));
    card.append(wrap);
    card.append(el("div", "shirt-add", "+ " + label));
    card.addEventListener("click", () => {
      if (isClub) { pickerMode = "teams"; }
      else { pickerMode = "players"; plActive = label; }
      syncPickerTabs();
      renderPickerTable();
      pickerTableWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    return card;
  }

  function renderPitch() {
    const positions = slotPositions();
    while (plan.picks.length < positions.length) plan.picks.push(null);
    plan.picks.length = positions.length;

    pitchEl.replaceChildren();
    SLOT_ORDER.forEach((pos) => {
      const idxs = positions
        .map((p, i) => (p === pos ? i : -1))
        .filter((i) => i >= 0);
      if (!idxs.length) return;
      const line = el("div", "pitch-line");
      idxs.forEach((index) => {
        const id = plan.picks[index];
        const row = id && POOL_BY_ID.get(id);
        line.append(row ? shirt(row, index) : emptyShirt(pos, index, false));
      });
      pitchEl.append(line);
    });

    const clubLine = el("div", "pitch-line pitch-clubline");
    for (let index = 0; index < 2; index++) {
      const name = plan.clubs[index];
      const club = name && DATA.clubs.find((c) => c.name === name);
      clubLine.append(club ? clubBadge(club, index) : emptyShirt("CLUB", index, true));
    }
    pitchEl.append(clubLine);

    updatePlanTotals();
  }

  // ---- The popup breakdown -------------------------------------------
  const planModal = document.getElementById("planmodal");
  const planModalBox = document.getElementById("planmodalbox");
  function closeModal() { planModal.hidden = true; planModalBox.replaceChildren(); }
  planModal.addEventListener("click", (e) => { if (e.target === planModal) closeModal(); });

  function openPlayerModal(row, index) {
    planModalBox.replaceChildren();
    const bar = el("div", "modal-actions");
    const capBtn = el("button", "chip" + (row.id === plan.captain ? " on" : ""),
      row.id === plan.captain ? "Captain \\u2713" : "Make captain");
    capBtn.type = "button";
    capBtn.addEventListener("click", () => {
      plan.captain = (plan.captain === row.id) ? null : row.id;
      renderPlanner();
      openPlayerModal(row, index);
    });
    const remBtn = el("button", "chip danger", "Remove from team");
    remBtn.type = "button";
    remBtn.addEventListener("click", () => {
      plan.picks[index] = null;
      if (plan.captain === row.id) plan.captain = null;
      renderPlanner();
      closeModal();
    });
    const closeBtn = el("button", "chip", "Close");
    closeBtn.type = "button";
    closeBtn.addEventListener("click", closeModal);
    bar.append(capBtn, remBtn, closeBtn);
    planModalBox.append(bar);
    planModalBox.append(poolExpansion(row, renderPlanner));
    planModal.hidden = false;
  }

  function openClubModal(club) {
    planModalBox.replaceChildren();
    const bar = el("div", "modal-actions");
    const remBtn = el("button", "chip danger", "Remove from team");
    remBtn.type = "button";
    remBtn.addEventListener("click", () => {
      const i = plan.clubs.indexOf(club.name);
      if (i >= 0) plan.clubs[i] = null;
      renderPlanner();
      closeModal();
    });
    const closeBtn = el("button", "chip", "Close");
    closeBtn.type = "button";
    closeBtn.addEventListener("click", closeModal);
    bar.append(remBtn, closeBtn);
    planModalBox.append(bar);
    planModalBox.append(clubBreakdown(club, () => { refreshClubs(); renderPlanner(); }));
    planModal.hidden = false;
  }

  // ---- The picker (right) --------------------------------------------
  let pickerMode = "players";
  let plActive = "ALL";
  let plLeague = "ALL";
  let plHA = "ALL";                 // ALL | H | A
  const plClubs = new Set();        // empty means every club
  const plThresholds = { xp: null, ownMin: null, ownMax: null, cs: null, xg: null, winOdds: null };
  let plSearch = "";
  let plExpandId = null;
  let plExpandName = null;
  const plPlayerSort = { key: "xp", dir: "desc" };
  const plTeamSort = { key: "xp", dir: "desc" };
  const pickerTableWrap = document.getElementById("pickertable");
  const plFilters = document.getElementById("plfilters");
  const plSearchInput = document.getElementById("plsearch");

  function addPlayerBtn(row) {
    const b = el("button", "addbtn", "+");
    b.type = "button";
    const openIndex = firstOpenSlot(row);
    const already = plan.picks.indexOf(row.id) !== -1;
    const atLimit = clubCount(row.club) >= MAX_PER_CLUB;
    const blocked = already || openIndex === -1 || atLimit;
    b.disabled = blocked;
    b.title = already ? "already in your squad"
      : openIndex === -1 ? "no open " + row.pos + " slot"
      : atLimit ? "already have " + MAX_PER_CLUB + " from " + row.club
      : "add to team";
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      if (blocked) return;
      plan.picks[openIndex] = row.id;
      renderPlanner();
    });
    return b;
  }

  function addClubBtn(club) {
    const b = el("button", "addbtn", "+");
    b.type = "button";
    const openIndex = plan.clubs[0] == null ? 0 : (plan.clubs[1] == null ? 1 : -1);
    const already = plan.clubs.indexOf(club.name) !== -1;
    const blocked = already || openIndex === -1;
    b.disabled = blocked;
    b.title = already ? "already picked" : openIndex === -1 ? "both club slots full" : "add to team";
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      if (blocked) return;
      plan.clubs[openIndex] = club.name;
      renderPlanner();
    });
    return b;
  }

  // A player's club figures: clean-sheet chance, team xG, win odds and venue.
  const playerCs = (r) => { const c = clubOf(r); return c ? clubProb(c, "cs") : NaN; };
  const playerXg = (r) => { const c = clubOf(r); return c ? teamXg(c) : NaN; };
  const playerWinProb = (r) => { const c = clubOf(r); return c ? clubProb(c, "win") : NaN; };
  const playerHA = (r) => { const c = clubOf(r); return c ? (c.away ? "A" : "H") : null; };

  // Columns mirror the projections pages: value-shaded xPts/xMins plus
  // ownership, so the picker reads the same way. Shades span the shown rows.
  // Clean-sheet % shows for keepers and defenders, team xG for mids and
  // forwards; the All view shows both.
  function pickerPlayerColumns(rows) {
    const xpShade = shadeFor(rows, (r) => pointsFor(r), false);
    const minsShade = shadeFor(rows, (r) => stateFor(r.id).xmins, false);
    const winShade = shadeFor(rows, playerWinProb, false);
    const showCs = plActive === "ALL" || plActive === "GK" || plActive === "DEF";
    const showXg = plActive === "ALL" || plActive === "MID" || plActive === "FWD";
    const csShade = shadeFor(rows, playerCs, false);
    const xgShade = shadeFor(rows, playerXg, false);
    const cols = [
      { key: "add", label: "", sortable: false, value: () => 0, cell: (r) => addPlayerBtn(r) },
      { key: "name", label: "Player", numeric: false,
        value: (r) => r.name.toLowerCase(), cell: (r) => el("span", "pname", r.name) },
      { key: "club", label: "Team", numeric: false,
        value: (r) => r.club.toLowerCase(), cell: (r) => r.club },
      { key: "ha", label: "H/A", numeric: false,
        value: (r) => playerHA(r) || "", cell: (r) => playerHA(r) || "" },
      { key: "gap", label: "", sortable: false, value: () => 0, cell: () => "", cellClass: () => "gapcol" },
      { key: "xp", label: "xPts", align: "right",
        value: (r) => pointsFor(r), cell: (r) => fmt(pointsFor(r)), shade: xpShade },
      { key: "xmins", label: "xMins", align: "right",
        value: (r) => stateFor(r.id).xmins, cell: (r) => String(stateFor(r.id).xmins), shade: minsShade },
      { key: "own", label: "Own%", align: "right",
        value: (r) => r.own, cell: (r) => r.own.toFixed(1) },
      { key: "win", label: "Win", align: "right",
        value: (r) => oddsVal(playerWinProb(r)),
        cell: (r) => { const p = playerWinProb(r); return Number.isFinite(p) ? oddsStr(p) : ""; },
        shade: winShade },
    ];
    if (showCs) cols.push({ key: "cs", label: "CS%", align: "right",
      value: playerCs,
      cell: (r) => { const v = playerCs(r); return Number.isFinite(v) ? Math.round(v * 100) + "%" : ""; },
      shade: csShade });
    if (showXg) cols.push({ key: "txg", label: "Team xG", align: "right",
      value: playerXg,
      cell: (r) => { const v = playerXg(r); return Number.isFinite(v) ? v.toFixed(2) : ""; },
      shade: xgShade });
    return cols;
  }

  function pickerTeamColumns(rows) {
    const xpShade = shadeFor(rows, (c) => clubAdjusted(c) ? clubXp(c) : c.xp, false);
    return [
      { key: "add", label: "", sortable: false, value: () => 0, cell: (c) => addClubBtn(c) },
      { key: "name", label: "Club", numeric: false,
        value: (c) => c.name.toLowerCase(), cell: (c) => el("span", "pname", c.name) },
      { key: "ha", label: "H/A", numeric: false,
        value: (c) => c.away ? "A" : "H", cell: (c) => c.away ? "A" : "H" },
      { key: "gap", label: "", sortable: false, value: () => 0, cell: () => "", cellClass: () => "gapcol" },
      { key: "xp", label: "xPts", align: "right",
        value: (c) => clubAdjusted(c) ? clubXp(c) : c.xp,
        cell: (c) => fmt(clubAdjusted(c) ? clubXp(c) : c.xp),
        shade: (c) => clubAdjusted(c) ? null : xpShade(c) },
      { key: "win", label: "Win", align: "right",
        value: (c) => oddsVal(clubProb(c, "win")), cell: (c) => oddsStr(clubProb(c, "win")) },
      { key: "cs", label: "CS", align: "right",
        value: (c) => oddsVal(clubProb(c, "cs")), cell: (c) => oddsStr(clubProb(c, "cs")) },
    ];
  }

  function renderPickerTable() {
    const q = plSearch.trim().toLowerCase();
    // Position filter and the numeric thresholds only make sense for players.
    plFilters.hidden = pickerMode === "teams";
    plHABar.hidden = pickerMode === "teams";
    plFilterBar.hidden = pickerMode === "teams";
    if (pickerMode === "teams") {
      const rows = DATA.clubs.filter((c) =>
        (plLeague === "ALL" || c.div === plLeague) &&
        (!plClubs.size || plClubs.has(c.name)) &&
        (!q || c.name.toLowerCase().includes(q) || (c.opp || "").toLowerCase().includes(q)));
      sortableTable(pickerTableWrap, {
        columns: pickerTeamColumns(rows), rows: rows, sortState: plTeamSort,
        keyOf: (c) => c.name,
        rowClass: (c) => plan.clubs.indexOf(c.name) !== -1 ? "in-squad" : "",
        onRowClick: (c) => { plExpandName = plExpandName === c.name ? null : c.name; renderPickerTable(); },
        expandedKey: plExpandName,
        expand: (c) => clubBreakdown(c, () => { refreshClubs(); renderPlanner(); }),
        rerender: renderPickerTable,
      });
    } else {
      const t = plThresholds;
      const rows = DATA.pool.filter((r) =>
        (plActive === "ALL" || r.pos === plActive) &&
        (plLeague === "ALL" || r.div === plLeague) &&
        (plHA === "ALL" || playerHA(r) === plHA) &&
        (!plClubs.size || plClubs.has(r.club)) &&
        (t.xp == null || pointsFor(r) >= t.xp) &&
        (t.ownMin == null || r.own >= t.ownMin) &&
        (t.ownMax == null || r.own <= t.ownMax) &&
        (t.cs == null || (Number.isFinite(playerCs(r)) && playerCs(r) * 100 >= t.cs)) &&
        (t.xg == null || (Number.isFinite(playerXg(r)) && playerXg(r) >= t.xg)) &&
        (t.winOdds == null || (Number.isFinite(playerWinProb(r)) && oddsVal(playerWinProb(r)) <= t.winOdds)) &&
        (!q || r.name.toLowerCase().includes(q) || r.club.toLowerCase().includes(q)));
      sortableTable(pickerTableWrap, {
        columns: pickerPlayerColumns(rows), rows: rows, sortState: plPlayerSort,
        keyOf: (r) => r.id,
        rowClass: (r) => plan.picks.indexOf(r.id) !== -1 ? "in-squad" : "",
        onRowClick: (r) => { plExpandId = plExpandId === r.id ? null : r.id; renderPickerTable(); },
        expandedKey: plExpandId,
        expand: (r) => poolExpansion(r, renderPlanner),
        rerender: renderPickerTable,
      });
    }
  }

  function syncPickerTabs() {
    document.getElementById("picktab-players")
      .setAttribute("aria-selected", String(pickerMode === "players"));
    document.getElementById("picktab-teams")
      .setAttribute("aria-selected", String(pickerMode === "teams"));
  }

  function renderPlanner() { renderPitch(); renderPickerTable(); }

  const formationSelect = document.getElementById("planformation");
  Object.keys(FORMATIONS).forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    if (name === plan.formation) option.selected = true;
    formationSelect.append(option);
  });

  formationSelect.addEventListener("change", () => {
    // Keep whoever still fits the new shape rather than emptying the squad.
    const kept = plan.picks.filter(Boolean);
    plan.formation = formationSelect.value;
    const positions = slotPositions();
    plan.picks = positions.map(() => null);
    positions.forEach((pos, index) => {
      const candidate = kept.find((id) => {
        const row = POOL_BY_ID.get(id);
        return row && row.pos === pos && plan.picks.indexOf(id) === -1;
      });
      if (candidate) plan.picks[index] = candidate;
    });
    if (plan.picks.indexOf(plan.captain) === -1) plan.captain = null;
    renderPlanner();
  });

  function seedPlan() {
    if (FORMATIONS[DATA.squad.formation]) plan.formation = DATA.squad.formation;
    formationSelect.value = plan.formation;
    const positions = slotPositions();
    plan.picks = positions.map(() => null);
    const byPosition = {};
    (DATA.squad.playerIds || []).forEach((id) => {
      const row = POOL_BY_ID.get(id);
      if (!row) return;
      byPosition[row.pos] = byPosition[row.pos] || [];
      byPosition[row.pos].push(id);
    });
    positions.forEach((pos, index) => {
      const next = (byPosition[pos] || []).shift();
      if (next) plan.picks[index] = next;
    });
    plan.captain = DATA.squad.captain;
    plan.clubs = (DATA.squad.clubs || []).map((c) => c.name).slice(0, 2);
    renderPlanner();
  }
  document.getElementById("planseed").addEventListener("click", seedPlan);

  document.getElementById("planclear").addEventListener("click", () => {
    plan.picks = slotPositions().map(() => null);
    plan.clubs = [];
    plan.captain = null;
    renderPlanner();
  });

  // Picker tabs (Players / Teams).
  document.getElementById("picktab-players").addEventListener("click", () => {
    pickerMode = "players"; syncPickerTabs(); renderPickerTable();
  });
  document.getElementById("picktab-teams").addEventListener("click", () => {
    pickerMode = "teams"; syncPickerTabs(); renderPickerTable();
  });

  // Position filter for the players picker.
  [["ALL", "All"], ["GK", "GK"], ["DEF", "DEF"], ["MID", "MID"], ["FWD", "FWD"]]
    .forEach(([code, label]) => {
      const b = el("button", "chip", label);
      b.type = "button";
      b.dataset.pos = code;
      b.setAttribute("aria-pressed", String(code === plActive));
      b.addEventListener("click", () => {
        plActive = code;
        plFilters.querySelectorAll(".chip").forEach((c) =>
          c.setAttribute("aria-pressed", String(c.dataset.pos === code)));
        renderPickerTable();
      });
      plFilters.append(b);
    });

  // League filter (applies to both the players and teams pickers).
  const plLeagueBar = document.getElementById("plleague");
  [["ALL", "All"], ["CH", "Champ"], ["L1", "Lg 1"], ["L2", "Lg 2"]]
    .forEach(([code, label]) => {
      const b = el("button", "chip", label);
      b.type = "button";
      b.dataset.lg = code;
      b.setAttribute("aria-pressed", String(code === plLeague));
      b.addEventListener("click", () => {
        plLeague = code;
        plClubs.clear();
        plLeagueBar.querySelectorAll(".chip").forEach((c) =>
          c.setAttribute("aria-pressed", String(c.dataset.lg === code)));
        buildPlClubPanel();
        updatePlClubBtn();
        renderPickerTable();
      });
      plLeagueBar.append(b);
    });

  // Club multi-select: tick any number of clubs; none ticked means all. The
  // list follows the league filter, so it never offers a club you can't see.
  const plClubBtn = document.getElementById("plclubbtn");
  const plClubPanel = document.getElementById("plclubpanel");
  function plClubList() {
    return DATA.clubs
      .filter((c) => plLeague === "ALL" || c.div === plLeague)
      .map((c) => c.name).sort();
  }
  function updatePlClubBtn() {
    plClubBtn.textContent = plClubs.size === 0
      ? "All clubs"
      : plClubs.size + " club" + (plClubs.size === 1 ? "" : "s");
  }
  function buildPlClubPanel() {
    plClubPanel.replaceChildren();
    const allLabel = document.createElement("label");
    const allBox = document.createElement("input");
    allBox.type = "checkbox";
    allBox.checked = plClubs.size === 0;
    allBox.addEventListener("change", () => {
      plClubs.clear();
      buildPlClubPanel();
      updatePlClubBtn();
      renderPickerTable();
    });
    allLabel.append(allBox, document.createTextNode("All clubs"));
    plClubPanel.append(allLabel);
    plClubPanel.append(el("div", "msdiv"));
    plClubList().forEach((name) => {
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = plClubs.has(name);
      box.addEventListener("change", () => {
        if (box.checked) plClubs.add(name); else plClubs.delete(name);
        const allInput = plClubPanel.querySelector("label input");
        if (allInput) allInput.checked = plClubs.size === 0;
        updatePlClubBtn();
        renderPickerTable();
      });
      label.append(box, document.createTextNode(name));
      plClubPanel.append(label);
    });
  }
  plClubBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    plClubPanel.hidden = !plClubPanel.hidden;
    plClubBtn.setAttribute("aria-expanded", String(!plClubPanel.hidden));
  });
  document.addEventListener("click", (e) => {
    if (!plClubPanel.hidden && e.target.closest && !e.target.closest(".multiselect")) {
      plClubPanel.hidden = true;
    }
  });
  buildPlClubPanel();
  updatePlClubBtn();

  // Home / away filter.
  const plHABar = document.getElementById("plha");
  [["ALL", "H+A"], ["H", "Home"], ["A", "Away"]].forEach(([code, label]) => {
    const b = el("button", "chip", label);
    b.type = "button";
    b.dataset.ha = code;
    b.setAttribute("aria-pressed", String(code === plHA));
    b.addEventListener("click", () => {
      plHA = code;
      plHABar.querySelectorAll(".chip").forEach((c) =>
        c.setAttribute("aria-pressed", String(c.dataset.ha === code)));
      renderPickerTable();
    });
    plHABar.append(b);
  });

  // Numeric thresholds (players only). Win odds is a ceiling on the decimal
  // win price, so a lower value keeps only the shorter-priced (likelier) teams.
  const plFilterBar = document.getElementById("plfilterbar");
  (function buildPlFilterBar() {
    const addNum = (labelText, get, set, step) => {
      const item = el("div", "fitem");
      item.append(document.createTextNode(labelText));
      const input = document.createElement("input");
      input.type = "number";
      input.step = step || "0.1";
      input.min = "0";
      const cur = get();
      input.value = cur == null ? "" : String(cur);
      input.addEventListener("input", () => {
        const v = parseFloat(input.value);
        set(Number.isFinite(v) ? v : null);
        renderPickerTable();
      });
      item.append(input);
      plFilterBar.append(item);
    };
    addNum("xPts \\u2265", () => plThresholds.xp, (v) => { plThresholds.xp = v; });
    addNum("Own% \\u2265", () => plThresholds.ownMin, (v) => { plThresholds.ownMin = v; }, "1");
    addNum("Own% \\u2264", () => plThresholds.ownMax, (v) => { plThresholds.ownMax = v; }, "1");
    addNum("Team CS% \\u2265", () => plThresholds.cs, (v) => { plThresholds.cs = v; }, "1");
    addNum("Team xG \\u2265", () => plThresholds.xg, (v) => { plThresholds.xg = v; });
    addNum("Win odds \\u2264", () => plThresholds.winOdds, (v) => { plThresholds.winOdds = v; });
  })();

  plSearchInput.addEventListener("input", () => {
    plSearch = plSearchInput.value;
    renderPickerTable();
  });

  // Land on a filled pitch (the model's squad) with the players picker ready.
  syncPickerTabs();
  seedPlan();

  // View switching. Team Planner is the landing tab.
  const VIEWS = ["planner", "players", "clubs", "history"];
  function showView(name) {
    VIEWS.forEach((key) => {
      const view = document.getElementById("view-" + key);
      const tab = document.getElementById("tab-" + key);
      if (view) view.hidden = key !== name;
      if (tab) tab.setAttribute("aria-selected", String(key === name));
    });
  }
  VIEWS.forEach((name) => {
    const tab = document.getElementById("tab-" + name);
    if (tab) tab.addEventListener("click", () => showView(name));
  });
  showView("planner");

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


def _smoke_test(page: Path) -> str | None:
    """Run the built page under node, if it is available.

    The page is assembled by substituting into a template, so a patch that
    matches nothing fails silently while a neighbouring one applies. That
    produces code referencing a variable that was never declared -- which
    throws on the first list row and leaves the whole page blank, with the
    Python tests entirely unable to see it. Exactly that shipped once.

    Skipped without node rather than failing: the check is a safeguard, not a
    dependency.
    """
    import shutil
    import subprocess

    if shutil.which("node") is None:
        return None
    checker = Path(__file__).resolve().parent / "check_page.js"
    if not checker.exists():
        return None
    result = subprocess.run(
        ["node", str(checker), str(page)],
        capture_output=True, text=True, timeout=60,
    )
    return None if result.returncode == 0 else (result.stderr or "").strip()


def main() -> int:
    if not DATA.exists():
        print("no data -- run: python scripts/export_app_data.py", file=sys.stderr)
        return 1

    payload = json.loads(DATA.read_text(encoding="utf-8"))
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    OUTPUT.write_text(html, encoding="utf-8")

    failure = _smoke_test(OUTPUT)
    if failure:
        print(f"wrote {OUTPUT}, but its script throws:", file=sys.stderr)
        print(f"  {failure}", file=sys.stderr)
        return 1

    print(f"wrote {OUTPUT}  ({len(html) // 1024} KB)")
    print(f"  {payload['gameweek']}, locks {payload['deadline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
