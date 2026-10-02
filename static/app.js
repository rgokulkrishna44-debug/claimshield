const $ = (id) => document.getElementById(id);
const rupee = (n) => "₹" + Math.round(n).toLocaleString("en-IN");
const state = { policyId: null, policy: null, timer: null };

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  for (const k of kids) if (k != null) e.append(k);
  return e;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 4000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Something went wrong");
  return data;
}
const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function busy(btn, fn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
  try { await fn(); } catch (e) { toast(e.message); } finally { btn.disabled = false; btn.textContent = label; }
}

// ---------- Tabs ----------
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === b.dataset.tab));
    $("need-policy").classList.toggle("hidden", !!state.policy);
    $("need-policy-2").classList.toggle("hidden", !!state.policy);
  })
);

// ---------- Status ----------
(async () => {
  const s = await api("/api/status");
  const pill = $("ai-status");
  pill.textContent = s.ai ? "AI on" + (s.bhashini ? " · Bhashini" : "") : "Rule engine only (no AI key)";
  pill.classList.toggle("on", s.ai);
  for (const [code, name] of Object.entries(s.languages)) $("lang").append(el("option", { value: code, textContent: name }));
})();
const lang = () => $("lang").value || "en";

// ---------- Policy ----------
const TERMS = [
  ["sum_insured", "Sum insured (₹)"],
  ["room_rent_limit_per_day", "Room rent limit (₹/day)"],
  ["room_rent_limit_pct_si", "Room rent limit (% of SI/day)"],
  ["icu_limit_per_day", "ICU limit (₹/day)"],
  ["icu_limit_pct_si", "ICU limit (% of SI/day)"],
  ["copay_pct", "Co-pay (%)"],
];

function showPolicy(data) {
  state.policyId = data.policy_id;
  state.policy = data.policy;
  const p = data.policy;
  $("policy-title").textContent = `${p.plan_name} · ${p.insurer}` + (data.used_ai ? "" : " (read without AI, please check)");
  const box = $("policy-terms");
  box.replaceChildren();
  for (const [key, label] of TERMS) {
    const input = el("input", { type: "number", value: p[key] ?? "", placeholder: "No limit" });
    input.addEventListener("input", () => { state.policy[key] = input.value === "" ? null : Number(input.value); });
    box.append(el("div", { className: "term" }, el("span", { textContent: label }), input));
  }
  const cons = el("input", { type: "checkbox", checked: p.consumables_cover });
  cons.addEventListener("change", () => (state.policy.consumables_cover = cons.checked));
  box.append(el("label", { className: "term check" }, cons, " Consumables add-on"));
  const subs = Object.entries(p.sub_limits || {}).map(([k, v]) => `${k}: ${rupee(v)}`).join(", ");
  if (subs) box.append(el("div", { className: "term" }, el("span", { textContent: "Sub-limits" }), subs));

  const cl = $("clauses");
  cl.replaceChildren();
  if (!data.clauses.length) cl.append(el("p", { className: "muted", textContent: "Turn on AI to pull out clauses automatically. You can still ask questions below." }));
  for (const c of data.clauses)
    cl.append(el("div", { className: "clause" }, el("b", { textContent: c.topic }), el("div", { textContent: c.plain_english }), el("q", { textContent: c.quote })));
  $("policy-out").classList.remove("hidden");
  $("need-policy").classList.add("hidden");
  $("need-policy-2").classList.add("hidden");
}

$("policy-demo").onclick = (e) => busy(e.target, async () => showPolicy(await api("/api/policy/demo", { method: "POST" })));
$("policy-upload").onclick = (e) => busy(e.target, async () => {
  const f = $("policy-file").files[0];
  if (!f) throw new Error("Choose a policy file first");
  const fd = new FormData();
  fd.append("file", f);
  showPolicy(await api("/api/policy/upload", { method: "POST", body: fd }));
});
$("ask").onclick = (e) => busy(e.target, async () => {
  if (!state.policyId) throw new Error("Load a policy first");
  const q = $("question").value.trim();
  if (!q) throw new Error("Type a question");
  const r = await postJSON("/api/policy/ask", { policy_id: state.policyId, question: q, lang: lang() });
  $("answer").textContent = r.answer;
  $("answer").classList.remove("hidden");
});

// ---------- Bill ----------
function addRow(item = { description: "", amount: "", days: "" }) {
  const desc = el("input", { value: item.description, placeholder: "e.g. Room rent" });
  const days = el("input", { type: "number", value: item.days ?? "", min: 1 });
  const amt = el("input", { type: "number", value: item.amount, min: 0 });
  const del = el("button", { className: "ghost", textContent: "✕", title: "Remove" });
  const tr = el("tr", {}, el("td", {}, desc), el("td", {}, days), el("td", {}, amt), el("td", {}, del));
  del.onclick = () => tr.remove();
  tr._get = () => ({ description: desc.value.trim(), amount: Number(amt.value), days: days.value ? Number(days.value) : null, category: item.category || null });
  $("bill-rows").append(tr);
}

function loadBill(b) {
  $("bill-rows").replaceChildren();
  b.items.forEach(addRow);
  $("treatment").value = b.treatment || "";
  $("diff-billing").checked = b.differential_billing !== false;
  state.hospital = b.hospital;
}

$("add-row").onclick = () => addRow();
$("bill-demo").onclick = (e) => busy(e.target, async () => loadBill(await api("/api/bill/demo")));
$("bill-upload").onclick = (e) => busy(e.target, async () => {
  const f = $("bill-file").files[0];
  if (!f) throw new Error("Choose a bill file first");
  const fd = new FormData();
  fd.append("file", f);
  const r = await api("/api/bill/upload", { method: "POST", body: fd });
  loadBill(r.bill);
  toast(`Read ${r.bill.items.length} lines` + (r.used_ai ? " with AI" : ". Please check them"));
});

$("run-audit").onclick = (e) => busy(e.target, async () => {
  if (!state.policy) throw new Error("Load a policy in step 1 first");
  const items = [...$("bill-rows").children].map((tr) => tr._get()).filter((i) => i.description && i.amount > 0);
  if (!items.length) throw new Error("Add at least one bill line");
  const r = await postJSON("/api/audit", {
    policy: state.policy,
    bill: { hospital: state.hospital || "Hospital", treatment: $("treatment").value, differential_billing: $("diff-billing").checked, items },
    lang: lang(),
  });
  $("s-total").textContent = rupee(r.total_billed);
  $("s-ins").textContent = rupee(r.insurer_pays);
  $("s-you").textContent = rupee(r.you_pay);
  $("s-chal").textContent = rupee(r.challengeable);

  $("summary").replaceChildren(...r.summary.map((s) => el("li", { textContent: s })));
  const tr = $("summary-tr");
  tr.classList.toggle("hidden", !r.summary_translated);
  if (r.summary_translated) tr.textContent = r.summary_translated.text;

  const rows = $("audit-rows");
  rows.replaceChildren();
  for (const l of r.lines) {
    const why = el("div", { className: "reason" });
    l.reasons.forEach((x) => why.append(el("div", { textContent: x })));
    if (l.rules.length) why.append(el("div", { className: "rule", textContent: "Rule: " + l.rules.join("; ") }));
    if (l.action) why.append(el("div", { className: "act", textContent: "→ " + l.action }));
    const protectedLine = l.cut === 0 && l.reasons.some((x) => x.startsWith("Protected"));
    rows.append(el("tr", { className: l.cut > 0 ? "cut" : protectedLine ? "protected" : "" },
      el("td", { textContent: l.description }),
      el("td", { className: "num", textContent: rupee(l.billed) }),
      el("td", { className: "num", textContent: rupee(l.payable) }),
      el("td", { className: "num", textContent: l.cut ? "−" + rupee(l.cut) : "" }),
      el("td", {}, why)));
  }
  $("audit-out").classList.remove("hidden");
  $("audit-out").scrollIntoView({ behavior: "smooth" });
});

// 3 hour discharge timer
$("timer-start").onclick = () => {
  clearInterval(state.timer);
  const end = Date.now() + 3 * 3600 * 1000;
  const d = $("timer-display");
  const tick = () => {
    const left = end - Date.now();
    const a = Math.abs(left);
    const h = Math.floor(a / 3600000), m = Math.floor((a % 3600000) / 60000), s = Math.floor((a % 60000) / 1000);
    const t = `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    d.textContent = left >= 0 ? t : "Late by " + t;
    d.classList.toggle("late", left < 0);
  };
  tick();
  state.timer = setInterval(tick, 1000);
  $("timer-start").textContent = "Restart timer";
};

// ---------- Rejection ----------
$("rej-demo").onclick = (e) => busy(e.target, async () => {
  $("rej-text").value = (await api("/api/rejection/demo")).letter;
  $("years").value = 5.5;
});

$("rej-run").onclick = (e) => busy(e.target, async () => {
  if (!state.policyId) throw new Error("Load a policy in step 1 first");
  const fd = new FormData();
  fd.append("policy_id", state.policyId);
  fd.append("years_insured", $("years").value || 0);
  fd.append("letter_text", $("rej-text").value);
  const f = $("rej-file").files[0];
  if (f) fd.append("file", f);
  fd.append("details", JSON.stringify({
    name: $("d-name").value, patient: $("d-patient").value, policy_no: $("d-policy").value,
    claim_no: $("d-claim").value, hospital: $("d-hospital").value, amount: $("d-amount").value, phone: $("d-phone").value,
  }));
  const r = await api("/api/rejection", { method: "POST", body: fd });
  const a = r.analysis;
  const verdictText = a.challengeable
    ? { strong: "Strong case to challenge", medium: "Worth challenging", weak: "Weak case, but you can still ask for a review" }[a.strength]
    : "This rejection looks valid under your policy";
  const v = $("verdict");
  v.replaceChildren(
    el("h2", { className: "verdict-" + (a.challengeable ? a.strength : "weak"), textContent: verdictText }),
    el("p", {}, el("b", { textContent: "Insurer's reason: " }), a.insurer_reason),
    el("b", { textContent: "Why you can push back:" }),
    el("ul", {}, ...a.grounds.map((g) => el("li", { textContent: g }))),
  );
  if (!r.used_ai) v.append(el("p", { className: "muted small", textContent: "Checked with built-in rules. Turn on AI for a full policy comparison." }));
  $("letter").value = r.letter;
  $("timeline").replaceChildren(...r.timeline.map((t) =>
    el("li", {}, el("b", { textContent: t.to }), el("div", { textContent: t.how }), el("div", { className: "muted small", textContent: `${t.wait} Start by: ${t.start_by}` }))));
  $("rej-out").classList.remove("hidden");
  $("rej-out").scrollIntoView({ behavior: "smooth" });
});

$("copy-letter").onclick = async () => {
  await navigator.clipboard.writeText($("letter").value);
  toast("Letter copied");
};
$("tr-letter").onclick = (e) => busy(e.target, async () => {
  if (lang() === "en") throw new Error("Pick a language at the top first");
  const r = await postJSON("/api/translate", { text: $("letter").value, lang: lang() });
  const box = $("letter-tr");
  box.textContent = r.engine === "none" ? "Translation needs an AI key or Bhashini key." : r.text + "\n\n(Send the English letter to the insurer. This copy is for you to understand it.)";
  box.classList.remove("hidden");
});
