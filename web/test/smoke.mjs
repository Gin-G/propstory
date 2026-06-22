// Headless smoke test: load the front end, run a real GDEX query, capture the
// run log + a screenshot + total time. Surfaces in-browser implementation issues
// (zarrita reading GDEX, point-read latency, time decoding, geocoding/CORS).
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE_URL || "http://localhost:8080";
// bypass geocoding to isolate GDEX read performance (Kremmling property)
const URL = `${BASE}/?lat=40.06&lon=-106.39`;
const YEARS = process.env.YEARS || "2";
const TIMEOUT_MS = +(process.env.TIMEOUT_MS || 540000);

fs.mkdirSync("artifacts", { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (m) => console.log("PAGE>", m.text()));
page.on("pageerror", (e) => console.log("PAGEERR>", e.message));

const t0 = Date.now();
await page.goto(URL, { waitUntil: "domcontentloaded" });
await page.fill("#years", YEARS);
await page.click("#go");

let logText = "";
while (Date.now() - t0 < TIMEOUT_MS) {
  logText = (await page.textContent("#log")) || "";
  if (/DONE\.|ERROR:/.test(logText)) break;
  await page.waitForTimeout(2000);
}
const elapsed = ((Date.now() - t0) / 1000).toFixed(1);

await page.screenshot({ path: "artifacts/web_screenshot.png", fullPage: true });
fs.writeFileSync("artifacts/web_log.txt", logText);
const snapshot = await page.textContent("#tbl").catch(() => "");
fs.writeFileSync("artifacts/web_table.txt", snapshot || "");

console.log(`\n===== TOTAL WALL TIME: ${elapsed}s =====`);
console.log("===== RUN LOG =====\n" + logText);
await browser.close();

if (!/DONE\./.test(logText)) {
  console.log("RESULT: did not reach DONE (see log/errors above)");
  process.exit(1);
}
console.log("RESULT: success");
