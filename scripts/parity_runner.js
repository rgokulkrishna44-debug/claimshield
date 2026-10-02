// Reads audit cases as JSON on stdin, runs the browser engine on each, prints results as JSON.
// Used by tests/test_parity.py to prove static/engine.js matches app/engine.py.
const fs = require("fs");
const path = require("path");
const engine = require(path.join(__dirname, "..", "static", "engine.js"));
engine.loadRules(JSON.parse(fs.readFileSync(path.join(__dirname, "..", "static", "rules.json"), "utf8")));
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map((c) => (c.rents ? engine.roomOptions(c.policy, c.items, c.rents, c.days, c.differential_billing, c.treatment) : engine.audit(c.policy, c.bill)));
process.stdout.write(JSON.stringify(out));
