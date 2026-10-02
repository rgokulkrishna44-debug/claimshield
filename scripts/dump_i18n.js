// Prints the text dictionary as JSON so tests can check it.
const path = require("path");
process.stdout.write(JSON.stringify(require(path.join(__dirname, "..", "static", "i18n.js")).DICT));
