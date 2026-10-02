/* ClaimShield rule engine for the browser. A line for line port of app/engine.py.
   tests/test_parity.py runs both engines on the same random bills and fails on any difference.
   Nothing here talks to a server: the bill never leaves the phone. */
(function (root) {
  "use strict";

  let R = null;
  let ENTRIES = [];
  let CAT_PATTERNS = {};

  function esc(s) {
    return s.replace(/[.*+?^${}()|[\]\\\/-]/g, "\\$&");
  }

  function termRegex(term) {
    if (typeof term === "object") return [new RegExp(term.re, "i"), term.w, term.label || term.re];
    if (term.endsWith("*")) return [new RegExp("\\b" + esc(term.slice(0, -1)), "i"), term.length - 1, term.slice(0, -1)];
    return [new RegExp("\\b" + esc(term) + "s?\\b", "i"), term.length, term];
  }

  function loadRules(data) {
    R = data;
    ENTRIES = [];
    let order = 0;
    for (const group of data.groups) {
      for (const term of group.terms) {
        const [rx, weight, label] = termRegex(term);
        ENTRIES.push({ weight, order: order++, rx, label, group });
      }
    }
    // Longest term first; ties keep file order. Must match app/rules.py exactly.
    ENTRIES.sort((a, b) => b.weight - a.weight || a.order - b.order);
    CAT_PATTERNS = {};
    for (const [cat, words] of Object.entries(data.category_keywords)) CAT_PATTERNS[cat] = words.map((w) => termRegex(w)[0]);
    return R;
  }

  function match(description) {
    for (const e of ENTRIES) if (e.rx.test(description)) return { group: e.group, term: e.label };
    return null;
  }

  function guessCategory(description) {
    for (const cat of R.category_order) if (CAT_PATTERNS[cat].some((rx) => rx.test(description))) return cat;
    return "other";
  }

  const r2 = (x) => Math.round((x + 1e-9) * 100) / 100;
  const truthy = (x) => x !== null && x !== undefined && x !== "" && Number(x) !== 0 && !Number.isNaN(Number(x));

  function limitOf(abs, pct, si) {
    const limits = [];
    if (truthy(abs)) limits.push(Number(abs));
    if (truthy(pct)) limits.push((Number(si) * Number(pct)) / 100);
    return limits.length ? Math.min(...limits) : null;
  }

  function audit(policy, bill) {
    const si = Number(policy.sum_insured);
    const roomLimit = limitOf(policy.room_rent_limit_per_day, policy.room_rent_limit_pct_si, si);
    const icuLimit = limitOf(policy.icu_limit_per_day, policy.icu_limit_pct_si, si);
    const assoc = new Set(R.associated);
    const noPd = new Set(R.no_pd);
    const diff = bill.differential_billing !== false;

    const cats = bill.items.map((it) => {
      const c = it.category || guessCategory(it.description);
      return R.categories.includes(c) ? c : "other";
    });
    const hasNursing = cats.includes("nursing");

    let ratio = null;
    bill.items.forEach((it, i) => {
      if (cats[i] === "room" && roomLimit) {
        const perDay = Number(it.amount) / (it.days || 1);
        if (perDay > roomLimit) {
          const r = roomLimit / perDay;
          ratio = ratio === null ? r : Math.min(ratio, r);
        }
      }
    });
    const applyRatio = ratio !== null && diff;

    const lines = bill.items.map((it, i) => {
      const cat = cats[i];
      const billed = Number(it.amount);
      let payable = billed;
      const codes = [], ruleCodes = [], params = {};
      let actionCode = null;
      let status = "ok";
      const hit = cat !== "room" && cat !== "icu" ? match(it.description) : null;
      const kind = hit ? hit.group.kind : null;
      if (hit) params.term = hit.term;

      if (kind === "not_payable") {
        ruleCodes.push(hit.group.rule);
        if (policy.consumables_cover) codes.push("LIST_I_ADDON");
        else { payable = 0; codes.push("LIST_I_NOT_PAID"); actionCode = "ACT_LIST_I"; }
      } else if (kind === "not_payable_if_nursing" && hasNursing) {
        payable = 0; ruleCodes.push(hit.group.rule); codes.push("SERVICE_CHARGE"); actionCode = "ACT_LIST_I";
      } else if (kind === "ambulance") {
        ruleCodes.push(hit.group.rule);
        if (policy.ambulance_cover) { codes.push("AMBULANCE_COVERED"); status = "check"; }
        else { payable = 0; codes.push("AMBULANCE_CHECK"); actionCode = "ACT_AMBULANCE"; }
      } else if (kind === "check") {
        ruleCodes.push(hit.group.rule); codes.push("TOILETRY_CHECK"); actionCode = "ACT_TOILETRY"; status = "check";
      } else if (kind === "subsumed") {
        payable = 0;
        const where = hit.group.where.toUpperCase();
        ruleCodes.push(hit.group.rule); codes.push("SUBSUMED_" + where); actionCode = "ACT_SUBSUMED_" + where;
      } else if (cat === "room" && roomLimit) {
        const days = it.days || 1;
        const allowed = roomLimit * days;
        if (billed > allowed) {
          payable = allowed;
          codes.push("ROOM_OVER"); ruleCodes.push("R_POLICY_ROOM"); actionCode = "ACT_ROOM";
          params.perDay = billed / days; params.limit = roomLimit;
        }
      } else if (cat === "icu") {
        if (icuLimit) {
          const days = it.days || 1;
          const allowed = icuLimit * days;
          if (billed > allowed) {
            payable = allowed;
            codes.push("ICU_OVER"); ruleCodes.push("R_POLICY_ICU");
            params.perDay = billed / days; params.limit = icuLimit;
          }
        }
        if (ratio !== null) { codes.push("ICU_NO_PD"); ruleCodes.push("R_PD"); status = "protected"; }
      }

      const pdEligible = hit === null && assoc.has(cat);
      if (applyRatio && pdEligible && payable > 0) {
        payable = payable * ratio;
        codes.push("PD_APPLIED"); ruleCodes.push("R_POLICY_PD");
        params.pct = ratio * 100;
        if (!actionCode) actionCode = "ACT_PD";
      } else if (ratio !== null && hit === null && noPd.has(cat) && cat !== "icu" && payable > 0) {
        codes.push("PD_PROTECTED"); ruleCodes.push("R_PD"); actionCode = "ACT_PROTECTED"; status = "protected";
      }

      const cut = billed - payable;
      if (cut > 0.004) status = "cut";
      return {
        description: it.description, category: cat, days: it.days || null, billed: r2(billed), payable: r2(payable),
        cut: r2(cut), status, codes, rule_codes: ruleCodes, params, action_code: actionCode,
      };
    });

    const total = lines.reduce((s, l) => s + l.billed, 0);
    let payableTotal = lines.reduce((s, l) => s + l.payable, 0);
    const summary = [];

    if (ratio !== null && !diff) summary.push({ code: "SUM_NO_DIFF" });

    let subLimitCut = 0;
    const treatment = (bill.treatment || "").toLowerCase().trim();
    for (const [name, cap] of Object.entries(policy.sub_limits || {})) {
      if (treatment && treatment.includes(name.toLowerCase()) && payableTotal > cap) {
        subLimitCut = payableTotal - cap;
        summary.push({ code: "SUM_SUBLIMIT", name, cap, cut: subLimitCut });
        payableTotal = cap;
      }
    }
    if (payableTotal > si) {
      summary.push({ code: "SUM_SI", si });
      payableTotal = si;
    }
    const copay = (payableTotal * Number(policy.copay_pct || 0)) / 100;
    const insurerPays = payableTotal - copay;
    if (copay) summary.push({ code: "SUM_COPAY", pct: Number(policy.copay_pct), amount: copay });

    const challengeable = lines.reduce((s, l) => s + (l.action_code && l.action_code.startsWith("ACT_SUBSUMED") ? l.cut : 0), 0);
    if (challengeable) summary.push({ code: "SUM_REMOVE", amount: challengeable });
    if (ratio !== null && diff) summary.push({ code: "SUM_PD", pct: ratio * 100 });

    return {
      lines, total_billed: r2(total), payable_before_copay: r2(payableTotal), copay: r2(copay),
      sub_limit_cut: r2(subLimitCut), insurer_pays: r2(insurerPays), you_pay: r2(total - insurerPays),
      room_ratio: ratio !== null ? Math.round(ratio * 1e4) / 1e4 : null, summary,
      summary_codes: summary.map((s) => s.code), challengeable: r2(challengeable),
    };
  }

  function roomOptions(policy, items, rents, days, differentialBilling, treatment) {
    days = days || 3;
    return rents.map((rent) => {
      const room = { description: "Room rent", category: "room", amount: rent * days, days };
      const r = audit(policy, { treatment: treatment || "", differential_billing: differentialBilling !== false, items: [room, ...items] });
      return { rent, days, you_pay: r.you_pay, insurer_pays: r.insurer_pays, total_billed: r.total_billed, room_ratio: r.room_ratio };
    });
  }

  const api = { loadRules, match, guessCategory, audit, roomOptions };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CSEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
