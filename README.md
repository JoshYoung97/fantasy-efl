# Fantasy EFL projections

Expected-points projections for the official [Fantasy EFL](https://fantasy.efl.com)
game: 7 players and 2 clubs per gameweek across all three EFL divisions.

Betting markets supply the fixture context, last season's Fantasy EFL stats
supply the player rates, and an exact solver picks the best legal squad.

Standard library only. No dependencies beyond `pytest` to run the tests.

---

## Why this game is not FPL

The rules differ in ways that change the whole approach:

- **No budget, no player prices, unlimited transfers.** There is no value or
  efficiency dimension at all. Projection accuracy *is* the entire product.
- **Interceptions score +2 each for midfielders, uncapped.** More than a goal
  (+6) for a player making three. This single rule makes ball-winning
  midfielders the dominant position, and it holds up empirically: the best
  midfielder projects around 3 points clear of the best player in any other
  position.
- **Rolling lockout.** Players lock at their own kickoff, not at one deadline.
  In GW1 that is 19 hours of extra time for most of the squad — long enough
  that confirmed line-ups are usually still actionable.
- **Doubles are routine, not rare.** 20 of 42 gameweeks contain a double, and
  they arrive in whole-division blocks (24, 48 or 72 clubs), never a handful.
  A club playing twice scores from both, so projections sum across fixtures.
  Where the market has priced only one of them — odds run three days ahead —
  the shortfall is reported rather than passed off as a whole gameweek.
- **Two clubs per gameweek, each usable 5 times per season.** A season-long
  allocation problem with no FPL equivalent, solved exactly by min-cost
  flow in `allocation.py` — greedy fails because using a club now costs one
  of only five chances and their best fixture may be months away. Doubles
  are not the constraint: 744 are available across the season for 84
  selections, so which clubs to spend uses on is the whole question.

---

## Setup

```bash
# 1. A free Odds API key: https://the-odds-api.com  (email only, no card)
powershell -ExecutionPolicy Bypass -File scripts/setup_credentials.ps1

# 2. First snapshot of the EFL feeds
python -m fantasy_efl.snapshot

# 3. Map EFL club names to bookmaker names (needs the key)
python scripts/build_club_mapping.py

# 4. The best legal squad
python scripts/optimal_team.py
```

Credentials are read from environment variables only — never from files, never
from arguments. `setup_credentials.ps1` prompts locally so they stay out of
shell history. On Mac or Linux, export `ODDS_API_KEY` however you normally
would.

**Budget:** each run costs 3 Odds API credits against a 500/month free tier.
Refreshing daily uses about 90. Keys are per person — sharing one means
everyone draws from the same 500 and it runs dry mid-season.

### Working from the same numbers

Odds move continuously, so the same code run an hour apart gives different
projections. Every live fetch is stored under `data/odds/` and committed, and
any script will replay the most recent one instead of fetching:

```bash
python scripts/optimal_team.py --stored-odds
```

That needs no API key at all and costs no credits, so a collaborator can pull
the repo and reproduce your numbers exactly before they have a key of their
own. It also builds an archive of what the market expected before each match,
which is what a proper check of the model against results will need.

One person should fetch live; everyone else replays. About 5 MB a season.

---

## Commands

| Command | Does |
|---|---|
| `python -m fantasy_efl.snapshot` | Capture the EFL feeds |
| `python scripts/optimal_team.py` | Best legal squad |
| `python scripts/player_projections.py` | Ranked players by position |
| `python scripts/export_app_data.py` | Data for the web page |
| `python scripts/build_app.py` | Build `data/app.html` |
| `node scripts/check_page.js` | Assert the built page's script runs |
| `node scripts/check_planner.js` | Drive the planner and check its total |
| `node scripts/check_live.js` | Drive the Live view at a frozen matchday |
| `python scripts/build_match_history.py` | Reconstruct match data from snapshots |
| `python scripts/plan_clubs.py --strength` | Plan club uses across the season |
| `python -m pytest tests/ -q` | 228 tests |

`optimal_team.py` takes:

- `--exclude Wing Clarke` — drop players after team news
- `--odds Swindon=1.4/0.5` — override a fixture's expected goals for/against
- `--one-club` — model the One Club chip
- `--proven-only` — exclude players with no EFL record

---

## How a projection is built

**Clubs** come straight from the market:

1. De-vig the exchange or bookmaker prices (raw prices sum to ~105%, so they
   are not probabilities until corrected — Shin's method by default).
2. Solve for both teams' Poisson scoring rates. 1X2 gives exactly two
   constraints for two parameters, so the rates are identified without
   spending credits on a totals market.
3. `5·P(win) + 3·P(draw) + 2·P(win ∧ away) + 2·P(CS) + 2·P(2+) + 2·P(4+)`

**Players** multiply three inputs — a rate, a fixture adjustment, and minutes —
then apply the scoring rules conditional on the minutes branch.

### The thing to understand before changing anything

Most scoring rules are **floor functions**: every 3 saves, every 4 clearances,
every 2 tackles. `E[floor(X/k)] ≠ E[X]/k`, because a player has to actually
reach each threshold.

Using `E[floor(X/k)] = Σ P(X ≥ jk)` over a negative binomial, a defender
averaging 0.72 tackles earns **0.18** points from the "every 2 tackles" rule,
not 0.36. The error is worst on low-rate stats, which is most stats for most
players.

Validated against a real 242-point season: the distributional method lands at
1.3% error, the naive one at 11.2%. If you change `expected.py`, keep this
property — `tests/test_scoring.py` will tell you if you haven't.

---

## Known gaps — read this before trusting a number

**`ADJUSTMENT_STRENGTH` (player_model.py) is the biggest open risk.** It sets
how hard fixture context moves a player's rates. At 1.0 defenders prefer hard
fixtures (defensive volume wins); at 0.5 they prefer easy ones (the undamped
clean sheet term wins). *The sign flips on a parameter nobody has measured*,
and it changes four of the seven optimal picks. Defaulted to 0.5 as the honest
midpoint. `tests/test_player_model.py` pins both behaviours so this cannot
drift silently.

Midfielders are unaffected in direction — they earn no clean sheet points, so
pressure is unopposed.

**About a third of all ownership sits on players the model cannot rate.** 571
selectable players have no EFL record, including the three most-owned players
in the game — ex-Premier League players at relegated clubs. They are projected
from position priors and rank low, so they are visible but never selected.
Resolves itself a few gameweeks into the season.

**The minutes model is calibrated, not measured.** The feed reports
appearances, not minutes, and counts a five-minute cameo the same as a full
match — worth about 0.5 points per appearance.

**Cards are assumed**, not fed. Position-level allowances in `CARD_COST`.

Both are now measurable. `scripts/build_match_history.py` differences the
snapshots into per-match lines and recovers minutes and cards from the points
residual — everything else in a score is observable, so the leftover is
appearance points less card deductions. It reports rather than applies: a
measured value only beats an assumption if the reconstruction behind it is
sound, and that needs looking at first. Run it after each gameweek.

On a simulated gameweek over the real pool it recovered a 0.723 start share as
0.749, and a defender card rate of 0.130 as 0.145.

**No multi-gameweek horizon, and no club strength rating.** Odds run three
days ahead. Worse, a single round cannot identify club strength at all: every
club appears exactly once, so only differences within a fixture are visible,
never levels across a division. The obvious substitute — last season's club
points — does not predict current market expectations (r = +0.12 overall,
−0.16 in League One).

`plan_clubs.py --strength` therefore weights clubs by their projected points
in the *current* round, which measures the fixture as much as the club. It is
a placeholder. Once several gameweeks have accumulated and clubs have met
different opponents, a proper rating becomes identifiable and the same solver
produces the real plan with no change to it.

---

## Snapshots are time-critical

The EFL feeds carry **season totals only**, no per-match rows. Differencing
consecutive snapshots is the only route to match-level data, which is what
will eventually fix the minutes model, the card gap and the unrateable
players.

A week not captured is gone. Totals stay correct — you lose the ability to
attribute stats to a specific match, which matters most in double gameweeks.

Two Windows scheduled tasks handle this (`FantasyEFL-Snapshot` twice daily,
`FantasyEFL-Refresh` daily). On other platforms, cron the same scripts.

**Snapshots are committed to this repo.** They are the project's least
replaceable asset. Commit them periodically rather than after every run, and
prefer one machine collecting rather than several producing divergent
histories.

---

## Layout

```
fantasy_efl/
  scoring.py       exact rules; doubles as the backtest oracle
  expected.py      projections, with correct floor-function expectations
  goals.py         solve Poisson rates from 1X2 prices
  odds.py          de-vigging: proportional, power, Shin, exchange midpoint
  oddsapi.py       The Odds API client
  betfair.py       read-only exchange client (unused; see its docstring)
  fpl_backfill.py  FPL goalkeeper backfill (does not work; see its docstring)
  club_names.py    EFL ↔ bookmaker club name matching
  player_model.py  rates, shrinkage, minutes, fixture adjustment
  projections.py   market prices → club projections
  optimiser.py     exact constrained squad selection
  pipeline.py      the whole chain, assembled once
  snapshot.py      feed capture and differencing
scripts/           runnable entry points
tests/             182 tests
data/              snapshots, club mapping, generated page
```

Two modules are dead ends kept deliberately, with the reasons in their
docstrings — `fpl_backfill.py` (the FPL API drops relegated clubs, so it
recovers nobody) and `betfair.py` (exchange prices arrive through the Odds API
already). Read those before rebuilding either.

---

## Contributing

Pull first, branch, then open a pull request:

```bash
git pull
git checkout -b what-you-are-changing
python -m pytest tests/ -q
git push -u origin what-you-are-changing
```

CI runs the full suite on every pull request against Python 3.10, 3.12 and
3.14, so a broken change cannot be merged. Run it locally anyway — it takes two
seconds and saves a round trip.

The tests encode the scoring rules, and several exist specifically to stop a
plausible-looking change from silently breaking the maths. Use branches for
anything touching the model: tests catch broken arithmetic, but not a bad
modelling judgement. `ADJUSTMENT_STRENGTH` is the obvious example — a change
there is defensible in either direction and deserves a second opinion.

If you change a projection, say what it does to the GW1 squad — the numbers in
this README came from real market prices and are worth keeping honest.

### Getting a change onto the phone page

Merging is not enough. `data/app.html` is generated and gitignored, and the
published page is a static artifact republished from Josh's machine. After a
merge, someone has to pull, re-run the export and build, and republish. Until
then everyone's phone shows the old numbers whatever `main` says.

### One snapshot collector

Only one machine should run the snapshot task. Several would produce divergent
histories of what is meant to be one canonical dataset. Commit snapshots
weekly rather than after every run, or the log fills with data churn.
