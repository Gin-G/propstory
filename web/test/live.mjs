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

const report = {
  url: URL,
  rendered_snow_before: before.snow,
  rendered_snow_after_chip: after.snow,
  avail_text: before.avail,
  log_before: before.log,
  log_after_chip: chipLog,
  records: after.records,
  console: consoleMsgs,
  request_failures: failed,
  http_4xx_5xx: http4xx,
};
fs.writeFileSync("artifacts/live_report.json", JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
