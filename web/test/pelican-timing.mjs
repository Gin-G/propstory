// Measure how fast a RECENT-WINDOW point read is through the Pelican director,
// to decide whether a live in-browser "recent conditions" preview is viable.
// ERA5 sfc stores are area-chunked, so a point time-series can fan out into
// many chunk fetches; this times reads of the last 30/90/365 days of snow depth
// at the Kremmling point and reports elapsed ms + bytes-ish so we know the real
// cost before wiring it into the app.
import { chromium } from "playwright";
import fs from "node:fs";

const DIRECTOR = "https://osdf-director.osg-htc.org";
const SD = `${DIRECTOR}/ncar/gdex/d633000/e5.oper.an.sfc.zarr/e5.oper.an.sfc.sd.zarr`;
const LAT = 40.0, LON = -106.5;             // Kremmling grid point
fs.mkdirSync("artifacts", { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto("https://example.com/", { waitUntil: "domcontentloaded" });

const out = await page.evaluate(async ({ base, lat, lon }) => {
  const t = (label, p) => { const a = performance.now(); return p.then((v) => ({ label, ms: Math.round(performance.now() - a), v })); };
  try {
    const zarr = await import("https://esm.sh/zarrita@0.4.0?bundle");
    const store = await zarr.withConsolidated(new zarr.FetchStore(base));
    const root = zarr.root(store);
    const open = (n) => zarr.open(root.resolve(n), { kind: "array" });

    const t0 = performance.now();
    const sd = await open("SD");
    const meta_ms = Math.round(performance.now() - t0);

    // coordinate arrays
    const cLat0 = performance.now();
    const latA = (await zarr.get(await open("latitude"))).data;
    const lonA = (await zarr.get(await open("longitude"))).data;
    const timeArr = await open("time");
    const timeV = (await zarr.get(timeArr)).data;
    const coord_ms = Math.round(performance.now() - cLat0);

    const lonE = ((lon % 360) + 360) % 360;
    const near = (arr, x) => { let b = 0, bd = Infinity; for (let i = 0; i < arr.length; i++) { const d = Math.abs(Number(arr[i]) - x); if (d < bd) { bd = d; b = i; } } return b; };
    const ilat = near(latA, lat), ilon = near(lonA, lonE);
    const end = timeV.length;

    // chunk shape (key to the cost)
    const chunks = sd.chunks;

    const windows = [30, 90, 365];
    const reads = [];
    for (const days of windows) {
      const steps = days * 24;                 // hourly
      const start = Math.max(0, end - steps);
      const a = performance.now();
      const { data } = await zarr.get(sd, [zarr.slice(start, end), ilat, ilon]);
      reads.push({ days, steps: end - start, ms: Math.round(performance.now() - a),
                   first: Number(data[0]), last: Number(data[data.length - 1]) });
    }
    return { ok: true, meta_ms, coord_ms, chunks, time_len: end,
             cell: [Number(latA[ilat]), ((Number(lonA[ilon]) + 180) % 360) - 180], reads };
  } catch (e) { return { ok: false, error: String(e) }; }
}, { base: SD, lat: LAT, lon: LON });

fs.writeFileSync("artifacts/pelican_timing.json", JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
await browser.close();
