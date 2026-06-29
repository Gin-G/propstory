// Diagnose the LIVE Pages site in a real browser: capture console messages,
// failed requests, HTTP>=400 responses, and whether data renders. Runs in CI
// (which can reach github.io). SITE_URL overrides the target.
import { chromium } from "playwright";
import fs from "node:fs";

const URL = process.env.SITE_URL || "https://gin-g.github.io/propstory/";
fs.mkdirSync("artifacts", { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();
const consoleMsgs = [], failed = [], http4xx = [];
page.on("console", (m) => consoleMsgs.push(`[${m.type()}] ${m.text()}`));
page.on("pageerror", (e) => consoleMsgs.push("PAGEERROR " + e.message));
page.on("requestfailed", (r) => failed.push(`${r.failure()?.errorText || "?"}  ${r.url()}`));
page.on("response", (r) => { if (r.status() >= 400) http4xx.push(`${r.status()}  ${r.url()}`); });

console.log("TARGET:", URL);
await page.goto(URL, { waitUntil: "load", timeout: 60000 });
await page.waitForTimeout(9000);                 // let index/auto-load/geocode run

const grab = async (s) => (await page.textContent(s).catch(() => "")).replace(/\s+/g, " ").trim();
const before = { avail: await grab("#avail"), snow: await grab("#s_snow"), log: await grab("#log") };

// try clicking the first precomputed-cell chip, if any
let chipLog = "(no chip found)";
const chip = await page.$("#avail button");
if (chip) { await chip.click(); await page.waitForTimeout(7000); chipLog = await grab("#log"); }

const after = { snow: await grab("#s_snow"), records: await grab("#tbl") };
await page.screenshot({ path: "artifacts/live.png", fullPage: true });

// Verify the deployed data index + that each advertised cell actually fetches.
let dataCheck = {};
try {
  const base = URL.endsWith("/") ? URL : URL + "/";
  dataCheck = await page.evaluate(async (base) => {
    const idx = await (await fetch(base + "data/index.json", { cache: "no-store" })).json();
    const keys = Object.keys(idx);
    const cells = {};
    for (const k of keys) {
      const r = await fetch(base + "data/" + k + ".json", { cache: "no-store" });
      const j = r.ok ? await r.json() : null;
      cells[k] = j
        ? { ok: true, peak_swe_in: j.means && j.means.peak_swe_in, water_years: j.water_years }
        : { ok: false, status: r.status };
    }
    return { keys, cells };
  }, base);
} catch (e) { dataCheck = { error: String(e) }; }

// Exercise the live ARCO path: an in-bbox cell that is NOT precomputed
// (39.5, -106.0) must render straight from the time-contiguous Zarr.
let arco = {};
try {
  const u = (URL.endsWith("/") ? URL : URL + "/") + "?lat=39.5&lon=-106.0";
  await page.goto(u, { waitUntil: "load", timeout: 60000 });
  await page.waitForFunction(() => window.__appReady === true, { timeout: 30000 });
  await page.click("#go");
  await page.waitForFunction(
    () => /DONE\./.test(document.getElementById("log")?.textContent || ""),
    { timeout: 45000 }).catch(() => {});
  arco = { snow: await grab("#s_snow"), wind: await grab("#s_wind"),
           records: await grab("#tbl"), log: await grab("#log") };
} catch (e) { arco = { error: String(e) }; }

const report = {
  url: URL,
  arco_live: arco,
  rendered_snow_before: before.snow,
  rendered_snow_after_chip: after.snow,
  avail_text: before.avail,
  log_before: before.log,
  log_after_chip: chipLog,
  records: after.records,
  data_check: dataCheck,
  console: consoleMsgs,
  request_failures: failed,
  http_4xx_5xx: http4xx,
};
fs.writeFileSync("artifacts/live_report.json", JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
