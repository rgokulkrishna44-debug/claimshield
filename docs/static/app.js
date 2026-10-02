/* ClaimShield web app. Runs fully on the phone: the rule engine, reading files, the letters.
   If it is served by the ClaimShield server with an AI key, it can also offer AI reading. */
(function () {
  "use strict";
  const { t, setLang, LANGS } = window.CSI18N;
  const E = window.CSEngine;
  const $ = (id) => document.getElementById(id);
  const STORE = "claimshield.v1";
  const CATS = ["room", "icu", "doctor", "nursing", "procedure", "pharmacy", "consumables", "implants", "diagnostics", "other"];

  // ---------- Sample data (made up on purpose) ----------
  const SAMPLE_POLICY = {
    insurer: "Bharat Sample General Insurance (demo)", plan_name: "Suraksha Family Health Plan",
    sum_insured: 500000, room_rent_limit_pct_si: 1, room_rent_limit_per_day: null, icu_limit_pct_si: 2,
    icu_limit_per_day: null, copay_pct: 0, consumables_cover: false, ambulance_cover: true,
  };
  const SAMPLE_CAPS = [{ name: "cataract", amount: 40000 }];
  const SAMPLE_POLICY_TEXT = [
    "Sum Insured: Rs 5,00,000 per policy year (family floater).",
    "Section 3.1 Room Rent: Room, boarding and nursing expenses are payable up to 1% of the Sum Insured per day.",
    "Section 3.2 ICU: Intensive care unit charges are payable up to 2% of the Sum Insured per day.",
    "Section 3.3 Proportionate Deduction: If the insured person occupies a room with rent higher than the eligible limit, all associated medical expenses shall be payable in the same proportion as the eligible room rent bears to the actual room rent. Pharmacy, consumables, implants, medical devices and diagnostics are not subject to proportionate deduction.",
    "Section 4.5 Sub-limits: Cataract surgery is payable up to Rs 40,000 per eye.",
    "Section 5.1 Pre-existing diseases are covered after 36 months of continuous coverage from the first policy start date.",
    "Section 5.4 Road ambulance charges are payable up to Rs 2,000 per hospitalisation.",
  ].join("\n");
  const SAMPLE_ITEMS = [
    { description: "Nursing charges", amount: 4500 },
    { description: "Surgeon fees", amount: 45000 },
    { description: "Anaesthetist fees", amount: 12000 },
    { description: "OT charges", amount: 18000 },
    { description: "Doctor visit charges", amount: 6000 },
    { description: "Pharmacy, medicines and injections", amount: 15600 },
    { description: "Surgical consumables (syringes, cannula, sutures)", amount: 6200 },
    { description: "Lab tests and CT scan", amount: 9800 },
    { description: "Gloves and masks", amount: 1450 },
    { description: "Admission kit", amount: 950 },
    { description: "Attendant food charges", amount: 2100 },
    { description: "Medical records and photocopy charges", amount: 400 },
    { description: "Registration charges", amount: 500 },
  ];
  const SAMPLE_BILL = {
    hospital: "Sri Lakshmi Multispeciality Hospital, Coimbatore (made up)",
    treatment: "Laparoscopic appendectomy",
    items: [{ description: "Room rent, deluxe single room (3 days)", amount: 24000, days: 3, category: "room" }, ...SAMPLE_ITEMS],
  };
  const SAMPLE_LETTER = [
    "Bharat Sample General Insurance Ltd (made up, for demo)",
    "Claim No: CL/2026/48213   Policy No: SFHP/21/0099812",
    "Date: 18 September 2026",
    "",
    "Dear Policyholder,",
    "We regret to inform you that your claim for hospitalisation at Sri Lakshmi Multispeciality Hospital from 10/09/2026 to 13/09/2026 for diabetes related complications has been repudiated.",
    "Reason: Non-disclosure of pre-existing diabetes at the time of taking the policy. As per our investigation the insured was on diabetes medication since 2019, which was not disclosed in the proposal form.",
    "",
    "The claim is therefore not admissible under the policy terms.",
    "Claims Department",
  ].join("\n");

  // ---------- State ----------
  const state = {
    lang: "en", policy: null, caps: [], policyText: "",
    admit: { days: 3, rents: ["", "", ""], items: [] },
    bill: { items: [], treatment: "", diff: true, hospital: "" },
    reject: { text: "", years: "", details: {} },
    timerStart: null, server: { up: false, ai: false },
    lastAudit: null, lastRooms: null, lastReject: null, tab: "bill",
  };

  function save() {
    try {
      const keep = { lang: state.lang, policy: state.policy, caps: state.caps, policyText: state.policyText,
        admit: state.admit, bill: state.bill, reject: state.reject, timerStart: state.timerStart };
      localStorage.setItem(STORE, JSON.stringify(keep));
    } catch (e) { /* private mode or storage blocked: the page still works */ }
  }
  function restore() {
    try {
      const s = JSON.parse(localStorage.getItem(STORE) || "null");
      if (s) Object.assign(state, s);
    } catch (e) { /* ignore */ }
  }

  // ---------- Helpers ----------
  const num = (x) => (x === "" || x === null || x === undefined || Number.isNaN(Number(x)) ? null : Number(x));
  const inr = (n) => Math.round(Number(n) || 0).toLocaleString("en-IN");
  const rupee = (n) => "₹" + inr(n);
  const pct = (x) => String(Math.round(x * 10) / 10);

  function el(tag, props, ...kids) {
    const e = document.createElement(tag);
    if (props) for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids) if (k !== null && k !== undefined && k !== false) e.append(k);
    return e;
  }

  function toast(msg) {
    const box = $("toast");
    box.textContent = msg;
    box.hidden = false;
    clearTimeout(box._h);
    box._h = setTimeout(() => (box.hidden = true), 4200);
  }

  async function busy(btn, fn) {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = t("working");
    try { await fn(); } catch (e) { toast(e.message || String(e)); } finally { btn.disabled = false; btn.textContent = label; }
  }

  function fmtParams(p) {
    const out = {};
    for (const [k, v] of Object.entries(p || {})) {
      if (k === "pct") out[k] = pct(v);
      else if (typeof v === "number") out[k] = inr(v);
      else out[k] = v;
    }
    return out;
  }

  // ---------- Language ----------
  function applyText() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-i18n]").forEach((n) => (n.textContent = t(n.dataset.i18n)));
    document.querySelectorAll("[data-i18n-ph]").forEach((n) => (n.placeholder = t(n.dataset.i18nPh)));
    $("mode").textContent = state.server.ai ? t("mode_ai") : state.server.up ? t("mode_server") : t("mode_local");
    document.querySelectorAll(".ai-only").forEach((n) => (n.hidden = !state.server.ai));
    renderChip();
    renderRows("bill-rows", state.bill.items, true);
    renderRows("admit-rows", state.admit.items, false);
    renderRoomInputs();
    if (state.lastAudit) renderAudit(state.lastAudit);
    if (state.lastRooms) renderRooms(state.lastRooms);
    if (state.lastReject) renderReject(state.lastReject);
    tick();
  }

  // ---------- Tabs ----------
  function showTab(id, push) {
    state.tab = id;
    document.querySelectorAll(".moment").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === id)));
    document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== id));
    $("policy-chip").hidden = id === "policy";
    if (push) history.replaceState(null, "", "#" + id);
  }

  // ---------- Policy ----------
  const POLICY_FIELDS = [
    ["p-si", "sum_insured"], ["p-room-abs", "room_rent_limit_per_day"], ["p-room-pct", "room_rent_limit_pct_si"],
    ["p-icu-abs", "icu_limit_per_day"], ["p-icu-pct", "icu_limit_pct_si"], ["p-copay", "copay_pct"],
  ];

  function policyForEngine() {
    if (!state.policy || !num(state.policy.sum_insured)) return null;
    const p = { ...state.policy, sub_limits: {} };
    for (const c of state.caps) if (c.name && num(c.amount)) p.sub_limits[c.name.trim().toLowerCase()] = num(c.amount);
    return p;
  }

  function fillPolicyForm() {
    const p = state.policy || {};
    for (const [id, key] of POLICY_FIELDS) $(id).value = p[key] ?? "";
    $("p-consumables").checked = !!p.consumables_cover;
    $("p-ambulance").checked = !!p.ambulance_cover;
    renderCaps();
  }

  function readPolicyForm() {
    const p = state.policy || { insurer: "Your insurer", plan_name: "Health policy" };
    for (const [id, key] of POLICY_FIELDS) p[key] = num($(id).value);
    p.copay_pct = p.copay_pct || 0;
    p.consumables_cover = $("p-consumables").checked;
    p.ambulance_cover = $("p-ambulance").checked;
    state.policy = p;
    save();
    renderChip();
  }

  function renderCaps() {
    const box = $("caps");
    box.replaceChildren(...state.caps.map((c, i) => el("div", { class: "cap" },
      el("input", { value: c.name || "", placeholder: t("pol_cap_name"), "aria-label": t("pol_cap_name"),
        oninput: (e) => { c.name = e.target.value; save(); } }),
      el("input", { type: "number", inputmode: "numeric", value: c.amount ?? "", placeholder: t("pol_cap_amount"),
        "aria-label": t("pol_cap_amount"), oninput: (e) => { c.amount = e.target.value; save(); } }),
      el("button", { class: "btn ghost small", type: "button", text: t("remove"),
        onclick: () => { state.caps.splice(i, 1); save(); renderCaps(); } }))));
  }

  function renderChip() {
    const chip = $("policy-chip");
    const p = policyForEngine();
    chip.replaceChildren();
    if (!p) {
      chip.append(el("span", { text: t("pol_missing") }), " ",
        el("button", { class: "linkish", type: "button", text: t("pol_sample"), onclick: useSamplePolicy }));
      return;
    }
    chip.append(el("span", { text: limitText(p) }), " ",
      el("button", { class: "linkish", type: "button", text: t("nav_policy"), onclick: () => showTab("policy", true) }));
  }

  function limitText(p) {
    const lim = [];
    if (num(p.room_rent_limit_per_day)) lim.push(num(p.room_rent_limit_per_day));
    if (num(p.room_rent_limit_pct_si)) lim.push((p.sum_insured * p.room_rent_limit_pct_si) / 100);
    return lim.length ? t("pol_summary", { si: inr(p.sum_insured), room: inr(Math.min(...lim)) }) : t("pol_summary_noroom", { si: inr(p.sum_insured) });
  }

  function useSamplePolicy() {
    state.policy = { ...SAMPLE_POLICY };
    state.caps = SAMPLE_CAPS.map((c) => ({ ...c }));
    state.policyText = SAMPLE_POLICY_TEXT;
    fillPolicyForm();
    save();
    renderChip();
    toast(t("pol_loaded_sample"));
  }

  async function readPolicyFile(file) {
    if (state.server.ai && $("ai-policy").checked) {
      toast(t("reading_ai"));
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("api/policy/upload", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      state.policy = { ...data.policy };
      state.caps = Object.entries(data.policy.sub_limits || {}).map(([name, amount]) => ({ name, amount }));
      state.policyText = data.text || "";
    } else {
      toast(t("reading_phone"));
      const text = await window.CSRead.fileText(file);
      state.policyText = text;
      const r = window.CSRead.parsePolicy(text);
      if (!r.found) { toast(t("pol_read_fail")); return; }
      state.policy = { insurer: "Your insurer", plan_name: "Health policy", ...r.policy };
    }
    fillPolicyForm();
    save();
    renderChip();
    toast(t("pol_read_done"));
  }

  function askPolicy() {
    const q = $("ask-q").value.trim();
    const box = $("ask-a");
    box.hidden = false;
    if (!state.policyText) { box.textContent = t("ask_need_text"); return; }
    const hits = window.CSRead.keywordAnswer(q, state.policyText);
    box.replaceChildren(hits.length ? el("p", { text: t("ask_found") }) : el("p", { text: t("ask_none") }),
      ...hits.map((h) => el("blockquote", { text: h })));
  }

  // ---------- Editable bill rows ----------
  function renderRows(containerId, items, withRoom) {
    const box = $(containerId);
    box.replaceChildren(...items.map((it, i) => {
      if (!it.category) it.category = E.guessCategory(it.description || "");
      const cat = el("select", { "aria-label": t("col_type"), onchange: (e) => { it.category = e.target.value; it._manual = true; save(); toggleDays(); } },
        ...CATS.filter((c) => withRoom || (c !== "room")).map((c) => el("option", { value: c, text: t("cat_" + c) })));
      cat.value = it.category;
      const days = el("input", { type: "number", inputmode: "numeric", min: 1, value: it.days ?? "", placeholder: t("col_days"),
        "aria-label": t("col_days"), oninput: (e) => { it.days = num(e.target.value); save(); } });
      const toggleDays = () => (days.hidden = !(it.category === "room" || it.category === "icu"));
      toggleDays();
      const desc = el("input", { value: it.description || "", placeholder: t("col_charge"), "aria-label": t("col_charge"),
        oninput: (e) => { it.description = e.target.value; save(); },
        onchange: () => { if (!it._manual) { it.category = E.guessCategory(it.description); cat.value = CATS.includes(it.category) ? it.category : "other"; toggleDays(); save(); } } });
      const amt = el("input", { type: "number", inputmode: "decimal", min: 0, value: it.amount ?? "", placeholder: t("col_amount"),
        "aria-label": t("col_amount"), class: "amt", oninput: (e) => { it.amount = num(e.target.value); save(); } });
      const del = el("button", { class: "btn ghost small", type: "button", text: t("remove"),
        onclick: () => { items.splice(i, 1); save(); renderRows(containerId, items, withRoom); } });
      return el("div", { class: "row-edit" }, desc, el("div", { class: "row-meta" }, cat, days, amt, del));
    }));
  }

  function cleanItems(items) {
    return items.filter((i) => i.description && num(i.amount) > 0)
      .map((i) => ({ description: i.description.trim(), amount: num(i.amount), days: num(i.days), category: i.category || null }));
  }

  async function readBillFile(file, target, rerender) {
    let items;
    if (state.server.ai && $("ai-bill").checked) {
      toast(t("reading_ai"));
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("api/bill/upload", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      items = data.bill.items;
      if (data.bill.hospital) state.bill.hospital = data.bill.hospital;
    } else {
      toast(t("reading_phone"));
      const text = await window.CSRead.fileText(file, (p) => toast(t("reading_phone") + " " + p + "%"));
      items = window.CSRead.parseBill(text);
    }
    if (!items.length) { toast(t("read_fail")); return; }
    target.splice(0, target.length, ...items.map((i) => ({ ...i, category: i.category || E.guessCategory(i.description) })));
    save();
    rerender();
    toast(t("read_done", { n: items.length }));
  }

  // ---------- Bill audit ----------
  function runAudit() {
    const p = policyForEngine();
    if (!p) throw new Error(t("err_policy_first"));
    const items = cleanItems(state.bill.items);
    if (!items.length) throw new Error(t("err_no_lines"));
    state.bill.treatment = $("treatment").value;
    state.bill.diff = $("diff").checked;
    const r = E.audit(p, { hospital: state.bill.hospital, treatment: state.bill.treatment, differential_billing: state.bill.diff, items });
    state.lastAudit = r;
    save();
    renderAudit(r);
    $("audit-out").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderAudit(r) {
    $("audit-out").hidden = false;
    $("s-total").textContent = rupee(r.total_billed);
    $("s-ins").textContent = rupee(r.insurer_pays);
    $("s-you").textContent = rupee(r.you_pay);
    $("s-remove").textContent = rupee(r.challengeable);
    $("s-remove-box").hidden = !(r.challengeable > 0);

    const todo = r.summary.map((s) => t(s.code, fmtParams(s)));
    if (!todo.length) todo.push(t("res_all_good"));
    $("todo").replaceChildren(...todo.map((x) => el("li", { text: x })));

    const subsumed = r.lines.filter((l) => l.action_code && l.action_code.startsWith("ACT_SUBSUMED")).map((l) => l.description);
    $("desk").hidden = !subsumed.length;
    $("desk-text").textContent = t("res_desk_remove", { items: subsumed.join(", ") });

    $("lines").replaceChildren(...r.lines.map((l) => {
      const params = fmtParams(l.params);
      return el("li", { class: "line " + l.status },
        el("div", { class: "line-head" },
          el("span", { class: "line-name", text: l.description }),
          el("span", { class: "chip " + l.status, text: t("st_" + l.status) })),
        el("div", { class: "line-money" },
          l.cut > 0 ? el("s", { text: rupee(l.billed) }) : el("span", { text: rupee(l.billed) }),
          l.cut > 0 ? el("b", { text: rupee(l.payable) }) : null),
        ...l.codes.map((c) => el("p", { class: "why", text: t(c, params) })),
        l.rule_codes.length ? el("p", { class: "rule", text: t("res_rule") + ": " + l.rule_codes.map((c) => t(c)).join("; ") }) : null,
        l.action_code ? el("p", { class: "act", text: t(l.action_code) }) : null);
    }));
  }

  function whatsappSummary() {
    const r = state.lastAudit;
    if (!r) return "";
    const lines = [t("wa_title") + (state.bill.hospital ? ", " + state.bill.hospital : ""), "",
      `${t("wa_total")}: ${rupee(r.total_billed)}`, `${t("wa_ins")}: ${rupee(r.insurer_pays)}`, `${t("wa_you")}: ${rupee(r.you_pay)}`];
    if (r.challengeable > 0) lines.push(`${t("wa_remove")}: ${rupee(r.challengeable)}`);
    lines.push("", ...r.summary.map((s) => t(s.code, fmtParams(s))), "", t("wa_footer"), location.href.split("#")[0]);
    return lines.join("\n");
  }

  // ---------- Admission: room choice ----------
  function renderRoomInputs() {
    const box = $("rents");
    box.replaceChildren(...state.admit.rents.map((v, i) => el("label", { class: "field" },
      el("span", { text: t("admit_room_n", { n: i + 1 }) }),
      el("input", { type: "number", inputmode: "numeric", min: 0, value: v ?? "", oninput: (e) => { state.admit.rents[i] = e.target.value; save(); } }))));
    $("admit-days").value = state.admit.days ?? 3;
  }

  function runRooms() {
    const p = policyForEngine();
    if (!p) throw new Error(t("err_policy_first"));
    const items = cleanItems(state.admit.items);
    if (!items.length) throw new Error(t("err_no_lines"));
    const rents = state.admit.rents.map(num).filter((x) => x > 0);
    if (!rents.length) throw new Error(t("admit_rooms"));
    state.admit.days = num($("admit-days").value) || 3;
    const opts = E.roomOptions(p, items, rents, state.admit.days, true, "");
    state.lastRooms = { opts, limit: roomLimitOf(p) };
    save();
    renderRooms(state.lastRooms);
    $("rooms-out").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function roomLimitOf(p) {
    const lim = [];
    if (num(p.room_rent_limit_per_day)) lim.push(num(p.room_rent_limit_per_day));
    if (num(p.room_rent_limit_pct_si)) lim.push((p.sum_insured * p.room_rent_limit_pct_si) / 100);
    return lim.length ? Math.min(...lim) : null;
  }

  function renderRooms(data) {
    const { opts, limit } = data;
    const minPay = Math.min(...opts.map((o) => o.you_pay));
    const best = opts.filter((o) => o.you_pay === minPay).sort((a, b) => b.rent - a.rent)[0];
    $("rooms-out").hidden = false;
    $("rooms").replaceChildren(...opts.map((o) => {
      const over = limit !== null && o.rent > limit;
      return el("div", { class: "room " + (o.you_pay === minPay ? "best" : over ? "over" : "") },
        el("div", { class: "room-rent", text: rupee(o.rent) + " " + t("per_day") }),
        el("span", { class: "chip " + (over ? "cut" : "ok"), text: over ? t("admit_over") : t("admit_within") }),
        o.you_pay === minPay ? el("span", { class: "chip protected", text: t("admit_best") }) : null,
        el("div", { class: "room-pay" }, el("span", { text: t("admit_you_pay") }), el("b", { text: rupee(o.you_pay) })),
        el("div", { class: "room-ins" }, el("span", { text: t("admit_ins_pays") }), el("span", { text: rupee(o.insurer_pays) })),
        o.you_pay > minPay ? el("p", { class: "why", text: t("admit_diff", { rent: inr(o.rent), base: inr(best.rent), extra: inr(o.you_pay - minPay) }) }) : null);
    }));
  }

  // ---------- Discharge timer ----------
  function tick() {
    const d = $("timer-display");
    const msg = $("timer-msg");
    if (!state.timerStart) {
      d.textContent = "3:00:00";
      d.classList.remove("late");
      msg.hidden = true;
      $("timer-say").hidden = true;
      return;
    }
    const left = state.timerStart + 3 * 3600 * 1000 - Date.now();
    const a = Math.abs(left);
    const h = Math.floor(a / 3600000), m = Math.floor((a % 3600000) / 60000), s = Math.floor((a % 60000) / 1000);
    const txt = `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    d.textContent = left >= 0 ? txt + " " + t("timer_left") : t("timer_over", { t: txt });
    d.classList.toggle("late", left < 0);
    msg.hidden = left >= 0;
    $("timer-say").hidden = left >= 0;
  }

  // ---------- Rejection ----------
  async function readLetterFile(file) {
    toast(t("reading_phone"));
    const text = await window.CSRead.fileText(file, (p) => toast(t("reading_phone") + " " + p + "%"));
    $("rej-text").value = text.trim();
    state.reject.text = $("rej-text").value;
    save();
  }

  function runReject() {
    const text = $("rej-text").value.trim();
    if (!text) throw new Error(t("err_letter"));
    const details = {};
    document.querySelectorAll("[data-detail]").forEach((n) => (details[n.dataset.detail] = n.value));
    if (!details.insurer && state.policy && state.policy.insurer && state.policy.insurer !== "Your insurer") details.insurer = state.policy.insurer;
    state.reject = { text, years: $("rej-years").value, details };
    const analysis = window.CSReject.analyze(text, $("rej-years").value);
    state.lastReject = { analysis, details };
    save();
    renderReject(state.lastReject);
    $("rej-out").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderReject(data) {
    const { analysis, details } = data;
    $("rej-out").hidden = false;
    const v = analysis.challengeable ? { strong: "v_strong", medium: "v_medium", weak: "v_weak" }[analysis.strength] : "v_valid";
    const verdict = $("verdict");
    verdict.className = "verdict " + (analysis.challengeable ? analysis.strength : "weak");
    verdict.textContent = t(v);
    $("rej-reason").textContent = analysis.insurer_reason;
    $("grounds").replaceChildren(...analysis.grounds.map((g) => el("li", { text: t(g) })));
    $("letter").value = window.CSReject.letter(analysis, details, window.CSI18N.DICT.en);
    const locale = state.lang + "-IN";
    $("steps").replaceChildren(...window.CSReject.steps(new Date()).map((s) => el("li", {},
      el("b", { text: t(s.to) }), el("p", { text: t(s.how) }),
      el("p", { class: "muted", text: t(s.wait) + " " + t("step_by", { date: s.by.toLocaleDateString(locale, { day: "numeric", month: "long", year: "numeric" }) }) }))));
  }

  async function copy(text, okMsg) {
    try { await navigator.clipboard.writeText(text); toast(okMsg); }
    catch (e) {
      const ta = el("textarea", { class: "offscreen" });
      ta.value = text;
      document.body.append(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      toast(okMsg);
    }
  }

  // ---------- Demo ----------
  function loadSampleBill() {
    state.bill = { items: SAMPLE_BILL.items.map((i) => ({ ...i })), treatment: SAMPLE_BILL.treatment, diff: true, hospital: SAMPLE_BILL.hospital };
    $("treatment").value = state.bill.treatment;
    $("diff").checked = true;
    renderRows("bill-rows", state.bill.items, true);
    save();
  }
  function loadSampleEstimate() {
    state.admit = { days: 3, rents: [3000, 5000, 8000], items: SAMPLE_ITEMS.map((i) => ({ ...i })) };
    renderRoomInputs();
    renderRows("admit-rows", state.admit.items, false);
    save();
  }

  async function runDemo() {
    useSamplePolicy();
    loadSampleBill();
    loadSampleEstimate();
    showTab("bill", true);
    runAudit();
  }

  // ---------- Wiring ----------
  async function detectServer() {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 2500);
      const res = await fetch("api/status", { signal: ctrl.signal });
      clearTimeout(timer);
      if (!res.ok) return;
      const s = await res.json();
      state.server = { up: true, ai: !!s.ai };
    } catch (e) { /* static hosting: everything runs on the phone */ }
  }

  function wire() {
    const sel = $("lang");
    sel.replaceChildren(...Object.entries(LANGS).map(([code, name]) => el("option", { value: code, text: name })));
    sel.value = state.lang;
    sel.addEventListener("change", () => { state.lang = setLang(sel.value); save(); applyText(); });

    document.querySelectorAll(".moment").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab, true)));
    $("demo").addEventListener("click", (e) => busy(e.target, runDemo));

    POLICY_FIELDS.forEach(([id]) => $(id).addEventListener("input", readPolicyForm));
    $("p-consumables").addEventListener("change", readPolicyForm);
    $("p-ambulance").addEventListener("change", readPolicyForm);
    $("p-sample").addEventListener("click", useSamplePolicy);
    $("cap-add").addEventListener("click", () => { state.caps.push({ name: "", amount: "" }); renderCaps(); });
    $("p-file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) busy($("p-file-btn"), () => readPolicyFile(f)); e.target.value = ""; });
    $("ask-btn").addEventListener("click", askPolicy);
    $("ask-q").addEventListener("keydown", (e) => { if (e.key === "Enter") askPolicy(); });

    $("admit-sample").addEventListener("click", loadSampleEstimate);
    $("admit-add").addEventListener("click", () => { state.admit.items.push({ description: "", amount: null }); renderRows("admit-rows", state.admit.items, false); });
    $("admit-file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) busy($("admit-file-btn"), () => readBillFile(f, state.admit.items, () => renderRows("admit-rows", state.admit.items, false))); e.target.value = ""; });
    $("admit-run").addEventListener("click", (e) => busy(e.target, async () => runRooms()));

    $("timer-start").addEventListener("click", () => { state.timerStart = Date.now(); save(); tick(); });
    $("timer-reset").addEventListener("click", () => { state.timerStart = null; save(); tick(); });
    setInterval(tick, 1000);

    $("bill-sample").addEventListener("click", loadSampleBill);
    $("bill-add").addEventListener("click", () => { state.bill.items.push({ description: "", amount: null }); renderRows("bill-rows", state.bill.items, true); });
    $("bill-file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) busy($("bill-file-btn"), () => readBillFile(f, state.bill.items, () => renderRows("bill-rows", state.bill.items, true))); e.target.value = ""; });
    $("treatment").addEventListener("input", (e) => { state.bill.treatment = e.target.value; save(); });
    $("diff").addEventListener("change", (e) => { state.bill.diff = e.target.checked; save(); });
    $("bill-run").addEventListener("click", (e) => busy(e.target, async () => runAudit()));
    $("copy-wa").addEventListener("click", () => copy(whatsappSummary(), t("res_copied")));

    $("rej-sample").addEventListener("click", () => { $("rej-text").value = SAMPLE_LETTER; $("rej-years").value = 5.5; state.reject.text = SAMPLE_LETTER; state.reject.years = 5.5; save(); });
    $("rej-file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) busy($("rej-file-btn"), () => readLetterFile(f)); e.target.value = ""; });
    $("rej-text").addEventListener("input", (e) => { state.reject.text = e.target.value; save(); });
    $("rej-run").addEventListener("click", (e) => busy(e.target, async () => runReject()));
    $("copy-letter").addEventListener("click", () => copy($("letter").value, t("rej_copied")));

    // File pickers sit behind friendly buttons.
    [["p-file-btn", "p-file"], ["admit-file-btn", "admit-file"], ["bill-file-btn", "bill-file"], ["rej-file-btn", "rej-file"]]
      .forEach(([b, f]) => $(b).addEventListener("click", () => $(f).click()));
  }

  async function start() {
    restore();
    if (!state.lang) state.lang = "en";
    const guess = (navigator.language || "en").slice(0, 2);
    try { if (!localStorage.getItem(STORE) && LANGS[guess]) state.lang = guess; } catch (e) { /* ignore */ }
    setLang(state.lang);
    const res = await fetch("static/rules.json");
    E.loadRules(await res.json());
    await detectServer();
    wire();
    fillPolicyForm();
    $("treatment").value = state.bill.treatment || "";
    $("diff").checked = state.bill.diff !== false;
    $("rej-text").value = state.reject.text || "";
    $("rej-years").value = state.reject.years || "";
    document.querySelectorAll("[data-detail]").forEach((n) => (n.value = (state.reject.details || {})[n.dataset.detail] || ""));
    applyText();
    const hash = location.hash.replace("#", "");
    showTab(["admit", "bill", "reject", "policy"].includes(hash) ? hash : "bill", false);
  }

  start().catch((e) => { console.error(e); toast(e.message || String(e)); });
})();
