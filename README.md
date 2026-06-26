# PropStory

**Enter an address → get its climate history (tables, plots, map) built from
NSF NCAR's Geoscience Data Exchange (GDEX).**

The data is GDEX ERA5 (`d633000`, hourly 1940–present, 0.25°) and, where higher
resolution matters, CONUS404 (`d559000`, 4 km). All weather/climate numbers
trace back to GDEX.

---

## How it works

```
address ──▶ geocode (browser) ──▶ snap to 0.25° ERA5 grid cell
                                        │
                       ┌────────────────┴───────────────┐
                       ▼                                 ▼
        FAST PATH (default)                ON-DEMAND PATH (uncached cell)
   fetch web/data/<cell>.json        open pre-filled "[cell-request]" issue
   (one ~45 KB request, instant)  ──▶  `on: issues` workflow reads GDEX,
                       │                commits the cell JSON, Pages redeploys
                       ▼                       (~2-3 min, then on fast path)
        tables · charts · records · map   (web/app.js)
```

### Why the precompute layer exists (the key finding)
GDEX's ERA5 stores are **area-chunked** (great for "a map at time T", bad for "one
point over many years" — a point fans out into thousands of chunk requests), so a
point time-series is slow to assemble. The deeper constraint: **GDEX serves no
CORS headers**, so a browser cannot read it at all — a cross-origin `fetch` fails
with `TypeError: Failed to fetch` (confirmed by a real-browser CI probe,
`web/test/gdex-cors.mjs`; `curl` masks this because it sends no `Origin`). GDEX
must therefore be read **server-side**, in CI.

The fix: precompute a **point-optimized** artifact. `build_cache.py` reads GDEX
once (in CI), aggregates hourly→**daily** + monthly climatology + records, and
writes a compact **one-file-per-cell JSON**. The browser fetches that same-origin
from Pages in a single request → instant. (Format: time-aggregated, point-local,
one file per cell. Sharded time-contiguous Zarr is the bigger-scale version.)

### On-demand cells (issue-triggered)
For an address with no precomputed cell, the front end opens a pre-filled
**`[cell-request]`** GitHub issue carrying the geocoded coordinates.
`cell-request.yml` (`on: issues`) parses them, runs `build_cache.py` against
GDEX, commits `web/data/<cell>.json` to `main`, and closes the issue; the push
redeploys Pages, putting the cell on the fast path. No server, no browser→GDEX
access required.

### Proven against GDEX (in CI)
- Stores are **Zarr v2 / consolidated**, read via PelicanFS/OSDF + xarray + dask.
- Real values land at the property for ERA5 (snow/temp/wind, 1940–2025).
- **GDEX is not browser-readable** (no CORS) — all GDEX access is server-side (CI).
- End-to-end pipeline verified: GDEX → cache JSON → headless-browser render.

---

## Layout

```
web/
  index.html        UI (address box, map, charts, tables)
  app.js            fast-path JSON render + on-demand "[cell-request]" issue opener
  data/<cell>.json  precomputed, point-optimized cells (GDEX-sourced)
  test/smoke.mjs    headless-browser test of the real flow
propstory/
  gdex.py           GDEX access recipe (ERA5 per-var Zarr, CONUS404 kerchunk/nc, retry)
  build_cache.py    GDEX → daily + climatology + records → web/data/<cell>.json
  build_era5.py     standalone ERA5 climatology report (CSV/PNG artifacts)
  gdex_probe.py     CI probe used to reverse-engineer GDEX access
.github/workflows/
  pipeline.yml      build cache (idempotent) → serve → headless smoke → commit + artifacts
  cell-request.yml  on: issues → build requested GDEX cell → commit → close issue
  gdex-cors.yml     real-browser probe proving GDEX has no CORS (server-side only)
  gdex-probe.yml    GDEX access probe (manual/iteration)
  web-test.yml      manual live-path smoke test
reports/            manual + data-driven property write-ups
```

## Run it

**Locally** (needs network to GDEX for live cells; precomputed cells work offline):
```bash
python -m http.server 8080 --directory web   # open http://localhost:8080
```

**Precompute a cell** (GDEX-sourced, run where GDEX is reachable, e.g. CI):
```bash
pip install -r requirements.txt
PROP_LAT=40.06 PROP_LON=-106.39 START_WY=2021 END_WY=2025 \
  python -m propstory.build_cache       # writes web/data/40.00_-106.50.json
```

**CI pipeline:** push to a `claude/**` branch (or run `pipeline.yml`) to build the
cache, render it in headless Chromium, commit the JSON, and upload the screenshot.

## Cell JSON schema (`propstory/era5-cell/v1`)
`property`, `grid_cell`, `water_years`, `means`, `records` (value + date),
`monthly_climatology`, `by_year[]`, and a compact `daily` series for the chart.

---

## Open items
- **Deployment / URL.** The app runs locally and in CI today. A public URL needs
  GitHub Pages (Pages on a *private* repo requires a paid plan) — or make the
  repo public, or host the static `web/` elsewhere.
- **Satellite imagery.** The map currently uses Esri World Imagery as a
  placeholder. Whether GDEX serves browsable Sentinel-2 is **unconfirmed** (its
  catalog search is client-rendered); needs resolution or a dedicated imagery
  source while keeping climate data on GDEX.
- **Coverage.** One cell is cached; generalize via a batch (region) precompute or
  on-demand (issue-triggered) cache generation.
- **Resolution caveat.** ERA5 0.25° (~31 km) smooths terrain and under-represents
  ridgetop wind/snow.
- **CONUS404 4 km feasibility (measured).** Its NetCDF variables are stored
  *contiguous* (not internally chunked, shape `(1, 1015, 1367)`), so each point
  read pulls the whole ~5.5 MB field; a point time series costs ~5.5 MB × hours ×
  vars (daily SNOWH ≈ 2 GB/yr/cell). Kerchunk references the same whole-field
  chunks, so it doesn't help. → CONUS404 can't be a responsive/scalable per-cell
  cache from GDEX's raw storage; only a slow one-off high-fidelity deep-dive
  (sparse sampling) is practical until a rechunked CONUS404 is available.
