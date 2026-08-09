// Drive the Live view at a frozen matchday moment.
//
// The rolling lockout is the one thing about this game that cannot be
// observed on the day the page is built: before the gameweek every player is
// open, so the locked branch never runs and a bug there ships unseen. This
// freezes the clock mid-gameweek -- after the Friday match and the 12:30
// kickoffs, before the 15:00 block -- so both branches execute.
//
// The property that matters: a replacement must itself still be unlocked.
// Suggesting a swap to a player whose match has already started is worse than
// suggesting nothing, because acting on it is impossible and the points are
// notional.
//
//     node scripts/check_live.js
const fs = require("fs");

const html = fs.readFileSync(process.argv[2] || "data/app.html", "utf8");
const script = html.split("<script>")[1].split("</script>")[0];
const data = JSON.parse(
  fs.readFileSync(process.argv[3] || "data/app_data.json", "utf8"));

// Saturday 15 Aug, 13:00 BST. Chosen from the real fixture list: the Friday
// 20:00 match and the twelve 12:30 kickoffs are gone, the fifty 15:00 ones
// have not started, and Sunday and Monday are days away.
const FROZEN = new Date("2026-08-15T13:00:00+01:00").getTime();
const RealDate = Date;
class FrozenDate extends RealDate {
  constructor(...args) {
    if (args.length === 0) super(FROZEN);
    else super(...args);
  }
  static now() { return FROZEN; }
}
global.Date = FrozenDate;

const byId = new Map();

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

new Function(script)();

let failures = 0;
const check = (label, ok, detail = "") => {
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "  " + detail : ""}`);
  if (!ok) failures++;
};

// Text of a node tree, since the stub does not compute it for parents.
const textOf = (n) =>
  n.textContent || (n.children || []).map(textOf).join(" ");

const kickoffOf = new Map(
  (data.clubs || []).map((c) => [c.name, c.kickoff]));
const lockedClub = (name) => {
  const k = kickoffOf.get(name);
  return k ? new RealDate(k).getTime() <= FROZEN : false;
};

function readRows() {
  const body = byId.get("livebody");
  return (body.children || [])
    .filter((c) => String(c.className).includes("liverow"))
    .map((row) => {
      const kids = row.children;
      const swapBox = kids.find((k) => String(k.className).includes("swap"));
      const cand = swapBox &&
        swapBox.children.find((k) => String(k.className).includes("cand"));
      const delta = swapBox &&
        swapBox.children.find((k) => String(k.className).includes("delta"));
      const button = swapBox && swapBox.children.find((k) => k.tag === "button");
      return {
        slot: textOf(kids[0]).trim(),
        name: textOf(kids[1].children[0]).trim(),
        sub: textOf(kids[1].children[1]).trim(),
        when: textOf(kids[2]).trim(),
        xp: parseFloat(textOf(kids[3])),
        locked: String(row.className).includes("shut"),
        cand: cand ? textOf(cand).trim() : null,
        gain: delta ? parseFloat(textOf(delta)) : null,
        button,
      };
    });
}

const rows = readRows();

console.log(`frozen at Sat 15 Aug 13:00 BST -- ${rows.length} squad slots`);
check("nine slots shown (7 players + 2 clubs)", rows.length === 9,
  String(rows.length));

const locked = rows.filter((r) => r.locked);
const open = rows.filter((r) => !r.locked);
check("both branches exercised", locked.length > 0 && open.length > 0,
  `${locked.length} locked, ${open.length} open`);

console.log("\nlocked slots are settled:");
check("no swap offered on a locked slot",
  locked.every((r) => r.cand === null),
  locked.filter((r) => r.cand).map((r) => r.name).join(", ") || "none offered");
check("locked slots read as locked",
  locked.every((r) => r.when === "locked"),
  locked.map((r) => r.when).join(" ") || "n/a");

// The model's own squad is optimal over the whole pool, and locking only
// ever removes candidates -- it cannot make an incumbent beatable. So the
// right answer here is silence, and anything else means the engine is
// inventing upgrades.
check("an already-optimal squad is left alone",
  rows.every((r) => r.cand === null),
  rows.filter((r) => r.cand).map((r) => r.name + " -> " + r.cand).join("; ") || "no changes urged");

// Clearing the squad is the reachable way to make the engine actually run:
// an empty slot is beaten by anyone, which is also the real team-news case
// (a player ruled out drops to zero and the same path fires).
console.log("\nrefilling an emptied squad:");
byId.get("planclear").click();
const emptied = readRows();
const suggested = emptied.filter((r) => r.cand);
check("every open slot offers a replacement",
  suggested.length === emptied.filter((r) => !r.locked).length,
  `${suggested.length} offered for ${emptied.filter((r) => !r.locked).length} open slots`);
check("the engine was actually exercised", suggested.length > 0,
  `${suggested.length} suggestions`);

// "Name  (Club)" for a player, "Name  (vs Opp)" for a club pick.
const parse = (text) => {
  const m = text.match(/^(.*?)\s\s\((.*)\)$/);
  return m ? { name: m[1].trim(), paren: m[2].trim() } : null;
};
const unreachable = [];
suggested.forEach((r) => {
  const bits = parse(r.cand);
  if (!bits) { unreachable.push(r.cand + " (unparsed)"); return; }
  const club = r.slot === "CLB" ? bits.name : bits.paren;
  if (lockedClub(club)) unreachable.push(`${bits.name} -> ${club}`);
});
check("every candidate's own match is still to come",
  unreachable.length === 0,
  unreachable.join("; ") || `${suggested.length} checked against kickoff times`);
check("every suggested swap is an improvement",
  suggested.every((r) => r.gain > 0),
  suggested.map((r) => r.gain.toFixed(2)).join(" "));

// The suggestions have to be a squad, not a list of nine answers to the same
// question. Two slots naming the same player is unactionable; two club slots
// naming the same club is not a legal squad at all.
const names = suggested.map((r) => parse(r.cand)).filter(Boolean).map((b) => b.name);
const dupes = names.filter((n, i) => names.indexOf(n) !== i);
check("no candidate is offered to two slots at once",
  dupes.length === 0, dupes.join(", ") || `${names.length} distinct`);

// The two-per-club cap applies to players only. A club selection is a
// separate pick, so two Boro players alongside Boro as a club is legal and
// must not be flagged.
const playerClubs = suggested
  .filter((r) => r.slot !== "CLB")
  .map((r) => parse(r.cand)).filter(Boolean).map((b) => b.paren);
const overUsed = [...new Set(playerClubs)].filter(
  (c) => playerClubs.filter((x) => x === c).length > 2);
check("no club supplies more than two players", overUsed.length === 0,
  overUsed.join(", ") || "within the two-per-club limit");

const clubPicks = suggested
  .filter((r) => r.slot === "CLB")
  .map((r) => parse(r.cand)).filter(Boolean).map((b) => b.name);
check("the two club slots name different clubs",
  new Set(clubPicks).size === clubPicks.length, clubPicks.join(", "));

console.log("\napplying one:");
const target = suggested[0];
const before = parseFloat(byId.get("plantotal").textContent);
target.button.click();
const after = parseFloat(byId.get("plantotal").textContent);
check("squad total rose", after > before, `${before} -> ${after}`);
check("the gain was the one advertised",
  Math.abs((after - before) - target.gain) < 0.02,
  `moved ${(after - before).toFixed(2)}, promised ${target.gain.toFixed(2)}`);
const refilled = readRows();
check("the slot is now filled",
  refilled.some((r) => parse(target.cand) &&
    r.name === parse(target.cand).name),
  parse(target.cand) ? parse(target.cand).name : target.cand);
check("still nine slots", refilled.length === 9, String(refilled.length));
check("no rule broken", byId.get("planwarn").textContent === "",
  byId.get("planwarn").textContent);

console.log(failures ? `\n${failures} failed` : "\nlive view behaves");
process.exit(failures ? 1 : 0);
