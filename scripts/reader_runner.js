// Runs the phone side bill parser and rejection checker on cases from stdin (for tests).
const fs = require("fs");
const path = require("path");
const read = require(path.join(__dirname, "..", "static", "read.js"));
const reject = require(path.join(__dirname, "..", "static", "reject.js"));
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({
  bills: cases.bills.map((t) => read.parseBill(t)),
  letters: cases.letters.map(([t, y]) => reject.analyze(t, y)),
}));
