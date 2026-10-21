// Renders the web UI with jsdom against fixture API responses (as served under an ingress prefix)
// and checks that every list renders. Run: npm install --no-save jsdom && node tests/ui/render.test.mjs
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const here = new URL(".", import.meta.url);
const html = readFileSync(new URL("../../wyoming_speaker_id/rootfs/usr/src/speaker_id/speaker_id/web/index.html", here), "utf8")
  .replaceAll("__VERSION__", "TEST");
const fixture = JSON.parse(readFileSync(new URL("fixture.json", here), "utf8"));
const base = "http://ha.local/api/hassio_ingress/TOKEN/";
let failed = 0;
const check = (cond, msg) => { console.log(`${cond ? "ok  " : "FAIL"} ${msg}`); if (!cond) failed++; };

async function render(lang) {
  const requested = [];
  const errors = [];
  const dom = new JSDOM(html, {
    url: base, runScripts: "dangerously", pretendToBeVisual: true,
    beforeParse(w) {
      Object.defineProperty(w.navigator, "language", { value: lang });
      w.fetch = async (url) => {
        const abs = new URL(url, base).href;
        requested.push(abs);
        const key = abs.startsWith(base) ? abs.slice(base.length) : abs;
        const body = fixture[key];
        return { ok: body !== undefined, status: body === undefined ? 404 : 200, json: async () => body ?? { error: "404 " + key } };
      };
      w.addEventListener("error", (e) => errors.push(e.message));
      w.console.error = (...a) => errors.push(a.join(" "));
    },
  });
  await new Promise((r) => setTimeout(r, 300));
  return { doc: dom.window.document, requested, errors, dom };
}

for (const lang of ["en-US", "ru-RU"]) {
  const { doc, requested, errors, dom } = await render(lang);
  const text = doc.querySelector("main").textContent;
  console.log(`--- ${lang}`);
  check(errors.length === 0, `no JS errors ${errors.join("; ")}`);
  check(requested.every((u) => u.startsWith(base)), "all API calls stay under the ingress prefix");
  check(!doc.body.innerHTML.includes("[object Object]"), "no [object Object]");
  check(doc.getElementById("err").hidden, "no error banner");
  const pTable = doc.getElementById("tbl_p_0");
  check(pTable && pTable.querySelectorAll("tbody tr").length === 2, "person sample table has 2 rows");
  check(pTable && pTable.textContent.includes("upload_20260101_120000_001.wav"), "person sample file name rendered");
  check(pTable && pTable.textContent.includes("turn on the light"), "person sample text rendered");
  check(doc.getElementById("tbl_p_1") !== null, "second person (quote in name) rendered");
  const cTable = doc.getElementById("tbl_c");
  check(cTable && cTable.querySelectorAll("tbody tr").length === 2, "cohort table has 2 rows");
  check(cTable && cTable.textContent.includes("a stranger talking"), "cohort text rendered");
  check(cTable && cTable.querySelectorAll("td.txt button").length === 1, "transcribe button for clip without text");
  check(doc.querySelectorAll("#recent tr").length === 2, "recent list has 2 rows");
  check(doc.querySelector("#recent .asg") !== null, "assignment badge shown");
  check(doc.getElementById("sliders").querySelectorAll("input[type=range]").length === 4, "4 sensitivity sliders");
  check(/faster-whisper/.test(doc.getElementById("up").textContent), "upstream connection shown");
  check(!/undefined|NaN/.test(text), "no 'undefined'/'NaN' in page text");
  // select-all checkbox on a person table must not throw
  const all = pTable.querySelector("thead input");
  all.checked = true; all.dispatchEvent(new dom.window.Event("change"));
  check([...pTable.querySelectorAll("tbody input")].every((c) => c.checked), "select-all works");
  dom.window.close();
}
if (failed) { console.error(`${failed} check(s) failed`); process.exit(1); }
console.log("UI render test passed");
