/* Reading documents on the phone itself: PDFs with pdf.js, photos with Tesseract.
   The files never leave the device. Libraries load from jsDelivr only when first needed. */
(function (root) {
  "use strict";

  const PDFJS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.min.mjs";
  const PDF_WORKER = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.worker.min.mjs";
  const TESSERACT = "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js";

  let pdfjsPromise = null;
  function loadPdfjs() {
    if (!pdfjsPromise) {
      pdfjsPromise = import(PDFJS).then((lib) => {
        // A same origin blob worker that imports the CDN worker, so the browser allows it.
        const blob = new Blob([`import "${PDF_WORKER}";`], { type: "text/javascript" });
        lib.GlobalWorkerOptions.workerSrc = URL.createObjectURL(blob);
        return lib;
      });
    }
    return pdfjsPromise;
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) return resolve();
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("Could not load " + src));
      document.head.append(s);
    });
  }

  async function pdfText(file) {
    const lib = await loadPdfjs();
    const doc = await lib.getDocument({ data: await file.arrayBuffer() }).promise;
    const lines = [];
    for (let p = 1; p <= doc.numPages; p++) {
      const page = await doc.getPage(p);
      const content = await page.getTextContent();
      const rows = [];
      for (const it of content.items) {
        if (!it.str || !it.str.trim()) continue;
        const x = it.transform[4], y = it.transform[5];
        let row = rows.find((r) => Math.abs(r.y - y) < 3);
        if (!row) { row = { y, parts: [] }; rows.push(row); }
        row.parts.push({ x, s: it.str });
      }
      rows.sort((a, b) => b.y - a.y);
      lines.push(`[Page ${p}]`);
      for (const r of rows) lines.push(r.parts.sort((a, b) => a.x - b.x).map((q) => q.s).join(" ").replace(/\s+/g, " ").trim());
    }
    return lines.join("\n");
  }

  async function imageText(file, onProgress) {
    await loadScript(TESSERACT);
    const worker = await root.Tesseract.createWorker("eng", 1, {
      logger: (m) => { if (onProgress && m.status === "recognizing text") onProgress(Math.round(m.progress * 100)); },
    });
    try {
      const { data } = await worker.recognize(file);
      return data.text || "";
    } finally {
      await worker.terminate();
    }
  }

  async function fileText(file, onProgress) {
    const type = file.type || "";
    if (type === "application/pdf" || /\.pdf$/i.test(file.name)) return pdfText(file);
    if (type.startsWith("image/")) return imageText(file, onProgress);
    return file.text();
  }

  // ---------- Bills ----------
  const LINE_RX = /^\s*(.+?)[\s:|,]+(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:\/-)?\s*$/i;
  const DAYS_RX = /(\d+)\s*(?:days?|nights?)\b/i;
  const SKIP_RX = /\b(total|sub ?total|grand total|discount|gst|cgst|sgst|tax|advance|deposit|balance|net payable|amount payable|amount due|bill no|bill date|uhid|ip no|mrn|reg no|page)\b/i;

  function money(s) { return Number(String(s).replace(/,/g, "")); }

  function parseBill(text) {
    const items = [];
    for (const raw of String(text).split(/\r?\n/)) {
      const line = raw.replace(/\s+/g, " ").trim();
      if (!line || SKIP_RX.test(line)) continue;
      const m = line.match(LINE_RX);
      if (!m) continue;
      let desc = m[1].replace(/(\s+[\d,.]+)+$/, "").replace(/^\d+[.)]\s*/, "").trim();
      const amount = money(m[2]);
      if (!(amount > 0) || desc.length < 3 || !/[a-z]/i.test(desc)) continue;
      const d = desc.match(DAYS_RX);
      items.push({ description: desc, amount, days: d ? Number(d[1]) : null });
    }
    return items;
  }

  // ---------- Policies ----------
  function parsePolicy(text) {
    const t = String(text).toLowerCase();
    const num = (re) => { const m = t.match(re); return m ? money(m[1]) : null; };
    const si = num(/sum insured[^0-9]{0,40}([\d,]{5,})/);
    const roomPct = num(/room rent[^%]{0,80}?(\d+(?:\.\d+)?)\s*%/);
    const roomAbs = roomPct ? null : num(/room rent[^0-9]{0,60}(?:rs\.?|₹|inr)\s*([\d,]{3,})/);
    const icuPct = num(/icu[^%]{0,80}?(\d+(?:\.\d+)?)\s*%/);
    const copay = num(/co\s?pay(?:ment)?[^%]{0,60}?(\d+(?:\.\d+)?)\s*%/);
    const found = [si, roomPct, roomAbs, icuPct, copay].some((x) => x !== null);
    return {
      found,
      policy: {
        sum_insured: si,
        room_rent_limit_pct_si: roomPct,
        room_rent_limit_per_day: roomAbs,
        icu_limit_pct_si: icuPct,
        icu_limit_per_day: null,
        copay_pct: copay || 0,
        consumables_cover: /consumable/.test(t) && /cover/.test(t) && !/not (?:opted|covered)/.test(t),
        ambulance_cover: /ambulance/.test(t) && !/ambulance[^.]{0,40}not covered/.test(t),
        sub_limits: {},
      },
    };
  }

  const STOP = new Set(["what", "does", "will", "covered", "cover", "policy", "much", "have", "with", "there", "this", "that", "from"]);
  function keywordAnswer(question, text) {
    const words = [...new Set((question.toLowerCase().match(/[a-z]{4,}/g) || []).filter((w) => !STOP.has(w)))];
    const sentences = String(text).split(/(?<=[.;])\s+|\n+/).map((s) => s.trim()).filter((s) => s.length > 20);
    const scored = sentences.map((s) => [words.filter((w) => s.toLowerCase().includes(w)).length, s]).filter((x) => x[0] > 0);
    scored.sort((a, b) => b[0] - a[0]);
    return scored.slice(0, 3).map((x) => x[1]);
  }

  const api = { fileText, pdfText, imageText, parseBill, parsePolicy, keywordAnswer };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CSRead = api;
})(typeof window !== "undefined" ? window : globalThis);
