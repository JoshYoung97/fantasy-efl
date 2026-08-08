// Drive the planner's real handlers against a stub DOM that records children
// and listeners, so clicks can actually be fired.
//
// The property this exists for: filling the planner from the model must
// produce the model's own total. The planner reuses pointsFor precisely so
// the two cannot diverge, and this is what proves they have not.
//
//     node scripts/check_planner.js
const fs = require("fs");

const html = fs.readFileSync(
  process.argv[2] || "data/app.html", "utf8");
const script = html.split("<script>")[1].split("</script>")[0];

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
    querySelector(sel) {
      const want = sel.replace(".", "");
      const walk = (n) =>
        n.children.find((c) => String(c.className).includes(want)) ||
        n.children.map(walk).find(Boolean);
      return walk(node) || null;
    },
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

const data = JSON.parse(
  fs.readFileSync(process.argv[3] || "data/app_data.json", "utf8"));

const total = byId.get("plantotal");
const note = byId.get("plannote");
const warn = byId.get("planwarn");
const slots = byId.get("planslots");

let failures = 0;
const check = (label, ok, detail = "") => {
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "  " + detail : ""}`);
  if (!ok) failures++;
};

console.log("empty planner:");
check("starts at zero", total.textContent === "0.00", total.textContent);
check("says nothing is picked", note.textContent.includes("0 of 7"), note.textContent);
check("seven empty slots drawn", slots.children.length === 7,
  String(slots.children.length));

console.log("\nfilling from the model:");
byId.get("planseed").click();
const seeded = parseFloat(total.textContent);
const expected = data.squad.total;
check("total matches the model's squad", Math.abs(seeded - expected) < 0.02,
  `planner ${seeded}  model ${expected}`);
check("all seven filled", note.textContent.includes("7 of 7"), note.textContent);
check("captain is set", note.textContent.includes("captain doubled"));
check("no rule broken", warn.textContent === "", warn.textContent);

console.log("\nchanging formation:");
const select = byId.get("planformation");
select.value = "1-3-2-1";
(select.listeners.change || []).forEach((fn) => fn());
check("still eight rows or fewer", slots.children.length === 7,
  String(slots.children.length));
check("total recomputed", parseFloat(total.textContent) > 0, total.textContent);

console.log("\nclearing:");
byId.get("planclear").click();
check("back to zero", total.textContent === "0.00", total.textContent);
check("no warnings left", warn.textContent === "");

console.log(failures ? `\n${failures} failed` : "\nplanner behaves");
process.exit(failures ? 1 : 0);
