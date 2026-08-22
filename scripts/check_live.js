// Drive the Live view at frozen matchday moments.
//
// The rolling lockout is the one thing about this game that cannot be observed
// on the day the page is built: before the gameweek every player is open, so
// the locked branch never runs and a bug there ships unseen.
//
// Two passes, both derived from the squad's own kickoffs rather than a
// hardcoded timestamp -- an earlier version froze at a fixed 13:00, which
// stopped exercising the locked branch the moment the odds moved and the model
// picked a squad that all kicked off later. Whatever the squad, one pass sits
// before every kickoff and one after, so both branches always execute.
//
// The property that matters: a replacement must itself still be unlocked.
// Suggesting a swap to a player whose match has started is worse than
// suggesting nothing, because acting on it is impossible.
//
//     node scripts/check_live.js
const fs = require("fs");

const html = fs.readFileSync(process.argv[2] || "data/app.html", "utf8");
const script = html.split("<script>")[1].split("</script>")[0];
const data = JSON.parse(
  fs.readFileSync(process.argv[3] || "data/app_data.json", "utf8"));

const RealDate = Date;
let failures = 0;
const check = (label, ok, detail = "") => {
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "  " + detail : ""}`);
  if (!ok) failures++;
};

const poolById = new Map(data.pool.map((p) => [p.id, p]));
const kickoffsOf = (row) => (row.fixtures || []).map((f) => f.kickoff).filter(Boolean);
const squadKickoffs = [
  ...data.squad.playerIds.flatMap((id) => kickoffsOf(poolById.get(id) || {})),
  ...data.squad.clubs.map((c) => c.kickoff),
].filter(Boolean).map((k) => new RealDate(k).getTime());

if (!squadKickoffs.length) {
  console.log("no kickoff times in the squad; nothing to check");
  process.exit(0);
}
const EARLIEST = Math.min(...squadKickoffs);
// The whole round, not just the squad: "everything is locked" has to mean
// every club the picker could offer, and a gameweek runs Friday to Monday.
// Taking the squad's own latest left Sunday and Monday clubs legitimately
// available, and the engine was right to offer them.
const ALL_KICKOFFS = (data.clubs || [])
  .map((c) => c.kickoff).filter(Boolean).map((k) => new RealDate(k).getTime());
const LATEST = Math.max(...squadKickoffs, ...ALL_KICKOFFS);
const HOUR = 3600 * 1000;

const kickoffByClub = new Map((data.clubs || []).map((c) => [c.name, c.kickoff]));

// ---- stub DOM, rebuilt for each pass ------------------------------------

function element(tag = "div") {
  const node = {
    tag, className: "", textContent: "", value: "", type: "", title: "",
    min: "", max: "", step: "", hidden: false, selected: false,
    style: {}, dataset: {}, children: [], listeners: {},
    classList: {
      add(...c) { node.className += " " + c.join(" "); },
      remove() {}, toggle() {}, contains: (c) => node.className.includes(c),
    },
    append(...kids) { kids.forEach((k) => k && node.children.push(k)); },
    appendChild(k) { node.children.push(k); },
    insertBefore() {}, remove() {}, focus() {}, scrollIntoView() {},
    replaceChildren() { node.children = []; },
    addEventListener(kind, fn) { (node.listeners[kind] ||= []).push(fn); },
    setAttribute(k, v) { node[k] = v; },
    getAttribute: (k) => node[k] ?? null,
    querySelector: () => null,
    querySelectorAll: () => [],
    click() { (node.listeners.click || []).forEach((fn) => fn({ stopPropagation() {} })); },
  };
  return node;
}

// The clock has to stay frozen for the whole pass, not just while the script
// first runs. Restoring it before the interactions meant every click -- and
// the re-render it triggers -- happened at real wall-clock time, so the
// assertions were checking a moment the test never intended.
function runAt(frozen, body) {
  const byId = new Map();
  global.document = {
    createElement: element,
    createTextNode: (t) => ({ textContent: t, children: [] }),
    getElementById: (id) => {
      if (!byId.has(id)) byId.set(id, element());
      return byId.get(id);
    },
    querySelector: () => element(),
    querySelectorAll: () => [],
    documentElement: element(),
    body: element(),
    addEventListener() {},
  };
  global.window = {
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    addEventListener() {},
  };
  global.setInterval = () => 0;
  global.setTimeout = () => 0;
  class FrozenDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(frozen); else super(...args);
    }
    static now() { return frozen; }
  }
  global.Date = FrozenDate;
  try {
    new Function(script)();
    body(byId);
  } finally {
    global.Date = RealDate;
  }
}

const textOf = (n) => n.textContent || (n.children || []).map(textOf).join(" ");

function readRows(byId) {
  return (byId.get("livebody").children || [])
    .filter((c) => String(c.className).includes("liverow"))
    .map((row) => {
      const kids = row.children;
      const swapBox = kids.find((k) => String(k.className).includes("swap"));
      const cand = swapBox &&
        swapBox.children.find((k) => String(k.className).includes("cand"));
      const delta = swapBox &&
        swapBox.children.find((k) => String(k.className).includes("delta"));
      return {
        slot: textOf(kids[0]).trim(),
        name: textOf(kids[1].children[0]).trim(),
        when: textOf(kids[2]).trim(),
        locked: String(row.className).includes("shut"),
        cand: cand ? textOf(cand).trim() : null,
        gain: delta ? parseFloat(textOf(delta)) : null,
        button: swapBox && swapBox.children.find((k) => k.tag === "button"),
      };
    });
}

const parse = (text) => {
  const m = text.match(/^(.*?)\s\s\((.*)\)$/);
  return m ? { name: m[1].trim(), paren: m[2].trim() } : null;
};

// ---- pass 1: before any kickoff -- everything open ----------------------

const BEFORE = EARLIEST - HOUR;
console.log(`pass 1  ${new RealDate(BEFORE).toISOString()}  (before every kickoff)`);
runAt(BEFORE, (byId) => {
const rows = readRows(byId);
check("nine slots shown (7 players + 2 clubs)", rows.length === 9, String(rows.length));
check("nothing is locked yet", rows.every((r) => !r.locked),
  rows.filter((r) => r.locked).map((r) => r.name).join(", ") || "all open");
check("an already-optimal squad is left alone", rows.every((r) => r.cand === null),
  rows.filter((r) => r.cand).map((r) => r.name).join("; ") || "no changes urged");

// Clearing is the reachable way to make the swap engine run: an empty slot is
// beaten by anyone, which is also the team-news case (a player ruled out drops
// to zero and the same path fires).
console.log("\n  refilling an emptied squad:");
byId.get("planclear").click();
const suggested = readRows(byId).filter((r) => r.cand);
check("the engine was actually exercised", suggested.length > 0,
  `${suggested.length} suggestions`);
const unreachable = [];
suggested.forEach((r) => {
  const bits = parse(r.cand);
  if (!bits) { unreachable.push(r.cand + " (unparsed)"); return; }
  const club = r.slot === "CLB" ? bits.name : bits.paren;
  const ko = kickoffByClub.get(club);
  if (ko && new RealDate(ko).getTime() <= BEFORE) unreachable.push(bits.name);
});
check("every candidate's own match is still to come", unreachable.length === 0,
  unreachable.join("; ") || `${suggested.length} checked against kickoff times`);
check("every suggested swap is an improvement", suggested.every((r) => r.gain > 0),
  suggested.map((r) => r.gain.toFixed(2)).join(" "));
const names = suggested.map((r) => parse(r.cand)).filter(Boolean).map((b) => b.name);
check("no candidate is offered to two slots at once",
  new Set(names).size === names.length,
  names.filter((n, i) => names.indexOf(n) !== i).join(", ") || `${names.length} distinct`);
const playerClubs = suggested.filter((r) => r.slot !== "CLB")
  .map((r) => parse(r.cand)).filter(Boolean).map((b) => b.paren);
check("no club supplies more than two players",
  playerClubs.every((c) => playerClubs.filter((x) => x === c).length <= 2),
  "within the two-per-club limit");
const clubPicks = suggested.filter((r) => r.slot === "CLB")
  .map((r) => parse(r.cand)).filter(Boolean).map((b) => b.name);
check("the two club slots name different clubs",
  new Set(clubPicks).size === clubPicks.length, clubPicks.join(", "));

console.log("\n  applying one:");
const target = suggested[0];
const before = parseFloat(byId.get("plantotal").textContent);
target.button.click();
const after = parseFloat(byId.get("plantotal").textContent);
check("squad total rose", after > before, `${before} -> ${after}`);
check("the gain was the one advertised",
  Math.abs((after - before) - target.gain) < 0.02,
  `moved ${(after - before).toFixed(2)}, promised ${target.gain.toFixed(2)}`);
check("still nine slots", readRows(byId).length === 9);
check("no rule broken", byId.get("planwarn").textContent === "",
  byId.get("planwarn").textContent);
});

// ---- pass 2: after every kickoff -- everything locked -------------------

console.log(`\npass 2  ${new RealDate(LATEST + HOUR).toISOString()}  (after every kickoff)`);
runAt(LATEST + HOUR, (byId) => {
const rows = readRows(byId);
check("every slot is locked", rows.every((r) => r.locked),
  rows.filter((r) => !r.locked).map((r) => r.name).join(", ") || "all locked");
check("locked slots read as locked", rows.every((r) => r.when === "locked"),
  [...new Set(rows.map((r) => r.when))].join(" "));
check("no swap is offered on a locked squad", rows.every((r) => r.cand === null),
  rows.filter((r) => r.cand).map((r) => r.name + " -> " + r.cand).join("; ") || "none");
// The decisive one: with every match started nothing can be brought in, so
// even an empty squad must have nothing to suggest.
byId.get("planclear").click();
const afterClear = readRows(byId).filter((r) => r.cand);
check("an emptied squad offers nobody once every match has started",
  afterClear.length === 0,
  afterClear.map((r) => r.slot + " -> " + r.cand).join("; ") || "none offered");
});

console.log(failures ? `\n${failures} failed` : "\nlive view behaves");
process.exit(failures ? 1 : 0);
