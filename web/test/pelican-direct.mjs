// Test whether a BROWSER can read GDEX Zarr by going through the OSDF/Pelican
// director directly (https://osdf-director.osg-htc.org/...) instead of GDEX's
// nginx alias (osdf-data.gdex.ucar.edu), whose 301 lacks CORS headers. The
// director (307) and the data caches (200/206) both return
// Access-Control-Allow-Origin: *, so the cross-origin redirect chain should
// pass CORS. We verify: (1) a simple GET, (2) a Range GET, (3) a real zarrita
// open + array read — all from a real cross-origin page context.
import { chromium } from "playwright";
import fs from "node:fs";

const DIRECTOR = "https://osdf-director.osg-htc.org";
const PATH = "/ncar/gdex/d633000/e5.oper.an.sfc.zarr/e5.oper.an.sfc.sd.zarr";
const META = `${DIRECTOR}${PATH}/.zmetadata`;
fs.mkdirSync("artifacts", { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();
const failures = [];
page.on("requestfailed", (r) => failures.push(`${r.failure()?.errorText || "?"}  ${r.url()}`));
// Real cross-origin context so the browser actually enforces CORS.
await page.goto("https://example.com/", { waitUntil: "domcontentloaded" });

const out = {};

// 1) simple GET through the director
out.simple_get = await page.evaluate(async (url) => {
  try {
    const r = await fetch(url, { cache: "no-store" });
    const t = await r.text();
    return { ok: r.ok, status: r.status, redirected: r.redirected, finalUrl: r.url,
             acao: r.headers.get("access-control-allow-origin"), bytes: t.length, head: t.slice(0, 60) };
  } catch (e) { return { error: String(e) }; }
}, META);

// 2) Range GET (Zarr chunk reads use Range; confirm it isn't preflight-blocked)
out.range_get = await page.evaluate(async (url) => {
  try {
    const r = await fetch(url, { headers: { Range: "bytes=0-99" }, cache: "no-store" });
    return { ok: r.ok, status: r.status, finalUrl: r.url, contentRange: r.headers.get("content-range") };
  } catch (e) { return { error: String(e) }; }
}, META);

// 3) Real zarrita open + read a coordinate array through the director
out.zarrita = await page.evaluate(async (base) => {
  try {
    const zarr = await import("https://esm.sh/zarrita@0.4.0?bundle");
    const store = await zarr.withConsolidated(new zarr.FetchStore(base));
    const latNode = await zarr.open(store.resolve("latitude"), { kind: "array" });
    const lat = await zarr.get(latNode);
    const n = lat.data.length;
    return { ok: true, lat_count: n, lat_first: Number(lat.data[0]), lat_last: Number(lat.data[n - 1]) };
  } catch (e) { return { ok: false, error: String(e) }; }
}, `${DIRECTOR}${PATH}`);

out.request_failures = failures;
fs.writeFileSync("artifacts/pelican_direct.json", JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
await browser.close();
