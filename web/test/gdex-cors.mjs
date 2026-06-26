// Diagnose whether GDEX/OSDF is reachable from a *browser* (CORS), which the
// live in-browser path needs. Run in CI (GitHub runners can reach GDEX). Tests
// a plain cross-origin fetch of a small Zarr metadata file the way the browser
// would, plus a manual-redirect probe to see if the OSDF director hands us off
// to a cache that drops CORS headers.
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "https://osdf-data.gdex.ucar.edu/ncar/gdex/d633000/e5.oper.an.sfc.zarr/e5.oper.an.sfc.sd.zarr";
fs.mkdirSync("artifacts", { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();
// Give the page a real origin so the browser enforces CORS on cross-origin fetches.
await page.goto("https://example.com/", { waitUntil: "domcontentloaded" });

const result = await page.evaluate(async (base) => {
  const out = {};
  // 1) The exact request zarrita makes: GET .zmetadata, redirects followed.
  try {
    const r = await fetch(base + "/.zmetadata", { cache: "no-store" });
    out.follow = { ok: r.ok, status: r.status, type: r.type, redirected: r.redirected, url: r.url,
                   acao: r.headers.get("access-control-allow-origin") };
    out.follow.bodyStart = (await r.text()).slice(0, 80);
  } catch (e) { out.follow = { error: String(e) }; }

  // 2) Manual redirect: reveal whether the director 30x-redirects us elsewhere.
  try {
    const r = await fetch(base + "/.zmetadata", { redirect: "manual", cache: "no-store" });
    out.manual = { status: r.status, type: r.type, location: r.headers.get("location") };
  } catch (e) { out.manual = { error: String(e) }; }

  return out;
}, BASE);

console.log(JSON.stringify(result, null, 2));
fs.writeFileSync("artifacts/gdex_cors.json", JSON.stringify(result, null, 2));
await browser.close();
