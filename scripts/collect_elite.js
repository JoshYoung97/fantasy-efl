// Collect the squads of the top-ranked managers, to compute elite ownership.
//
// Runs in the browser, on fantasy.efl.com, while logged in. Both endpoints it
// uses return 401 without a session, and the alternative -- copying a session
// cookie into a script -- means handling a credential that would then sit on
// disk and expire silently. Pasting this into the console keeps the session
// where it already is.
//
//   1. Open https://fantasy.efl.com/rankings and sign in
//   2. Open the console (F12)
//   3. Paste this whole file and press enter
//   4. It prints JSON; save it as data/elite_raw.json in the repo
//   5. Run: python scripts/build_elite_ownership.py
//
// Nothing useful comes back until a gameweek has locked -- before that every
// lineup is nulls, which the aggregation reports rather than hides.

(async () => {
  const TOP_N = 100;
  const PAGE_SIZE = 20;
  const DELAY_MS = 150;   // spacing, so 100 fetches are not a burst

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function api(path) {
    const response = await fetch(path, { credentials: "include" });
    if (!response.ok) throw new Error(`${path} -> HTTP ${response.status}`);
    const body = await response.json();
    if (body.errors && body.errors.length) {
      throw new Error(`${path} -> ${body.errors[0].message}`);
    }
    return body.success;
  }

  // Which round to read. The leaderboard is for the season; teams are per
  // round, so this takes the latest round that has actually been played.
  const rounds = await (await fetch("/json/fantasy/rounds.json")).json();
  const played = rounds
    .filter((r) => r.gameMode === "season")
    .filter((r) => (r.games || []).some((g) => g.homeScore !== null || g.isFinalized))
    .map((r) => r.roundNumber);
  const roundId = played.length ? Math.max(...played) : 1;

  console.log(`collecting top ${TOP_N} for round ${roundId}...`);

  // The site pages with limit and page, not an offset -- taken from how its
  // own store calls the endpoint, rather than assumed.
  const entries = [];
  let pageNumber = 1;
  while (entries.length < TOP_N) {
    const page = await api(
      `/api/en/season/rankings/overall_leaderboard?limit=${PAGE_SIZE}&page=${pageNumber}`);
    const rankings = page.leaderboard.rankings || [];
    if (!rankings.length) break;
    entries.push(...rankings);
    if (!page.leaderboard.nextPage) break;
    pageNumber++;
    await sleep(DELAY_MS);
  }
  const top = entries.slice(0, TOP_N);
  console.log(`  ${top.length} managers on the leaderboard`);

  const teams = [];
  let failed = 0;
  for (const entry of top) {
    try {
      const result = await api(
        `/api/en/season/other-user-team/${entry.userId}/${roundId}`);
      teams.push({
        userId: entry.userId,
        rank: entry.rank,
        overallPoints: entry.overallPoints,
        formation: result.team.formation,
        players: result.team.lineup.players,
        squads: result.team.lineup.squads,
        captainId: result.team.captainId,
        viceCaptainId: result.team.viceCaptainId,
        maxCaptain: result.team.maxCaptainEnabled,
        oneClub: result.team.oneClubEnabled,
      });
    } catch (error) {
      failed++;
      console.warn(`  ${entry.userId}: ${error.message}`);
    }
    await sleep(DELAY_MS);
  }

  const filled = teams.filter((t) =>
    Object.values(t.players || {}).flat().some((id) => id !== null)).length;

  const payload = {
    collectedAt: new Date().toISOString(),
    roundId,
    requested: TOP_N,
    collected: teams.length,
    withPicks: filled,
    failed,
    teams,
  };

  console.log(`  ${teams.length} teams, ${filled} with picks, ${failed} failed`);
  if (!filled) {
    console.log("  No squad has any picks yet -- teams stay hidden until a");
    console.log("  gameweek locks. Run this again after one has.");
  }
  console.log("\n--- copy everything below into data/elite_raw.json ---\n");
  console.log(JSON.stringify(payload));
  window.__elite = payload;
  return payload;
})();
