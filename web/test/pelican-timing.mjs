// Why a live in-browser point read is slow: inspect the ERA5 chunk shape and
// time the SMALLEST possible read (a single timestep at one point). If even one
// element forces a whole global-field chunk, the store is area-chunked and not
// suited to live point time-series — which is the precise thing to ask the data
// provider to fix (publish time-contiguous / point-optimized chunks).
import { chromium } from "playwright";
import fs from "node:fs";

const DIRECTOR = "https://osdf-director.osg-htc.org";
const SD = `${DIRECTOR}/ncar/gdex/d633000/e5.oper.an.sfc.zarr/e5.oper.an.sfc.sd.zarr`;
const LAT = 40.0, LON = -106.5;
fs.mkdirSync("artifacts", { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto("https://example.com/", { waitUntil: "domcontentloaded" });

const out = await page.evaluate(async ({ base, lat, lon }) => {
  const r = { steps: [] };
  try {
    const zarr = await import("https://esm.sh/zarrita@0.4.0?bundle");
    const store = await zarr.withConsolidated(new zarr.FetchStore(base));
    const root = zarr.root(store);
    const open = (n) => zarr.open(root.resolve(n), { kind: "array" });

    const sd = await open("SD");
    // Metadata only — no data fetched yet.
    r.sd_shape = sd.shape;
    r.sd_chunks = sd.chunks;
    r.sd_dtype = sd.dtype;
    const bytesPerChunk = sd.chunks.reduce((a, b) => a * b, 1) * 4; // float32-ish
    r.approx_bytes_per_chunk = bytesPerChunk;

    // small coords
    const latA = (await zarr.get(await open("latitude"))).data;
    const lonA = (await zarr.get(await open("longitude"))).data;
    const lonE = ((lon % 360) + 360) % 360;
    const near = (arr, x) => { let b = 0, bd = Infinity; for (let i = 0; i < arr.length; i++) { const d = Math.abs(Number(arr[i]) - x); if (d < bd) { bd = d; b = i; } } return b; };
    const ilat = near(latA, lat), ilon = near(lonA, lonE);
    const end = sd.shape[0];

    // THE key measurement: read ONE timestep at ONE point. With area-chunking
    // this still pulls a whole spatial slab (one chunk). Time it.
    const a = performance.now();
    const one = await zarr.get(sd, [end - 1, ilat, ilon]);
    r.single_point_single_step_ms = Math.round(performance.now() - a);
    r.single_value = Number(one.data ? one.data[0] : one);
    r.ok = true;
  } catch (e) { r.ok = false; r.error = String(e); }
  return r;
}, { base: SD, lat: LAT, lon: LON });

fs.writeFileSync("artifacts/pelican_timing.json", JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
await browser.close();
