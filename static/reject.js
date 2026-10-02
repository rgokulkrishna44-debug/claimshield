/* Checking a rejection letter against IRDAI rules, writing the complaint letter, and the
   escalation steps with dates. Runs on the phone; the same rules as app/extract.py. */
(function (root) {
  "use strict";

  function has(t, words) { return words.some((w) => t.includes(w)); }

  function analyze(text, years) {
    const raw = String(text || "");
    const t = raw.toLowerCase();
    years = Number(years) || 0;
    const m = raw.match(/reason\s*[:\-]\s*([\s\S]+?)(?:\n\s*\n|$)/i);
    const reason = (m ? m[1] : raw).replace(/\s+/g, " ").trim().slice(0, 400);
    const out = { insurer_reason: reason, reason_type: "other", challengeable: true, strength: "medium", grounds: [] };
    const mentionsPed = has(t, ["pre-existing", "pre existing", "preexisting"]) || /\bped\b/.test(t);

    if (has(t, ["non-disclosure", "non disclosure", "nondisclosure", "suppression", "not disclosed", "concealment", "misrepresentation"])) {
      out.reason_type = "non_disclosure";
      if (years >= 5) { out.strength = "strong"; out.grounds.push("G_MORATORIUM"); }
      else out.grounds.push("G_ND_ASK");
      if (mentionsPed && years >= 3) out.grounds.push("G_PED_CAP");
    } else if (mentionsPed) {
      out.reason_type = "pre_existing_disease";
      if (years >= 3) out.strength = "strong";
      out.grounds.push("G_PED_CAP", "G_PED_PROOF");
    } else if (t.includes("waiting period")) {
      out.reason_type = "waiting_period";
      out.grounds.push("G_WAITING_PORT");
    } else if (has(t, ["24 hours", "less than 24", "day care", "daycare"])) {
      out.reason_type = "day_care";
      out.grounds.push("G_DAYCARE");
    } else if (has(t, ["not medically necessary", "could have been treated", "opd", "outpatient", "out patient", "no active treatment"])) {
      out.reason_type = "not_medically_necessary";
      out.grounds.push("G_DOCTOR");
    } else if (has(t, ["document", "papers", "not submitted"])) {
      out.reason_type = "documents_missing";
      out.strength = "strong";
      out.grounds.push("G_DOCS");
    } else if (has(t, ["intimation", "intimated", "informed late", "late notice"])) {
      out.reason_type = "late_intimation";
      out.strength = "strong";
      out.grounds.push("G_LATE");
    } else if (has(t, ["room rent", "proportionate", "deduction"])) {
      out.reason_type = "room_rent_or_deduction";
      out.grounds.push("G_PD");
    }
    out.grounds.push("G_CRC");
    return out;
  }

  function letter(analysis, d, en) {
    const v = (x, fallback) => (x && String(x).trim()) || fallback;
    const name = v(d.name, "[Your name]");
    const lines = [
      `Date: ${new Date().toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}`,
      "",
      "To,",
      "The Grievance Redressal Officer,",
      v(d.insurer, "[Insurer name]"),
      "",
      `Subject: Review of claim ${v(d.claim, "[Claim number]")} under policy ${v(d.policy, "[Policy number]")}`,
      "",
      "Dear Sir or Madam,",
      "",
      `I am writing about the claim for ${v(d.patient, name)}'s treatment at ${v(d.hospital, "[Hospital name]")}. ` +
        `The claim was rejected or reduced with this reason: "${analysis.insurer_reason.slice(0, 300)}".`,
      "",
    ];
    if (d.amount) lines.push(`Amount disputed: Rs ${Number(d.amount).toLocaleString("en-IN")}`, "");
    lines.push("I request a review for these reasons:", "");
    analysis.grounds.forEach((g, i) => lines.push(`${i + 1}. ${en[g] || g}`));
    lines.push(
      "",
      "Under the IRDAI Master Circular on Health Insurance Business (29 May 2024), please also share the Claims " +
        "Review Committee's decision and the exact policy clause relied on.",
      "",
      "Please reconsider and settle the claim in full within 14 days. If it is not resolved, I will approach " +
        "IRDAI's Bima Bharosa portal and the Insurance Ombudsman.",
      "",
      "Documents attached:",
      "1. The insurer's rejection letter",
      "2. Policy schedule",
      "3. Discharge summary",
      "4. Final hospital bill and payment receipts",
      "",
      "Yours sincerely,",
      name,
      v(d.phone, "[Phone]"),
    );
    return lines.join("\n");
  }

  function steps(start) {
    const day = 86400000;
    const d0 = start || new Date();
    return [
      { to: "S1_to", how: "S1_how", wait: "S1_wait", by: d0 },
      { to: "S2_to", how: "S2_how", wait: "S2_wait", by: new Date(d0.getTime() + 14 * day) },
      { to: "S3_to", how: "S3_how", wait: "S3_wait", by: new Date(d0.getTime() + 30 * day) },
    ];
  }

  const api = { analyze, letter, steps };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CSReject = api;
})(typeof window !== "undefined" ? window : globalThis);
