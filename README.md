# PropStory

**Build the historical representation of any address from analysis-ready
geoscience data served by NSF NCAR's Geoscience Data Exchange (GDEX).**

Give PropStory a street address (or a lat/lon). It geocodes the location,
pulls the matching grid cell from **CONUS404** — NCAR/USGS's 4 km, ~40-year
(WY 1980–2022) hourly hydroclimate reanalysis — directly from **GDEX via the
Open Science Data Federation (OSDF)**, and renders a multi-decade "propstory":
how much it snows, whether a skiable base actually builds and holds, how windy
it is, and how all of that has trended over time.

This is the data-driven answer to questions like *"if I buy this ridge to ski
out my backyard, does it actually get — and hold — enough snow?"*

---

## Why CONUS404 from GDEX

- **Analysis-ready.** GDEX serves CONUS404 as cloud-optimized **Zarr**,
  streamable with `xarray` over **OSDF/PelicanFS** — no NCAR HPC account, no
  bulk download. See GDEX's OSDF integration: `https://gdex.ucar.edu/about-gdex/ndcc-osdf/`.
- **High resolution.** 4 km dynamical downscaling of ERA5 (WRF) resolves
  mountain terrain far better than the ~31 km ERA5 grid or a single valley
  weather station — important for a ridge that behaves nothing like the town
  below it.
- **Long and consistent.** Hourly, water years 1980–2022 — long enough to
  characterize *interannual variability and trend*, not just an average year.
- **The right variables.** Snow water equivalent (`SNOW`), snow depth
  (`SNOWH`), precipitation (`PREC_ACC_NC`), 2 m temperature (`T2`), and 10 m
  winds (`U10`,`V10`).

GDEX dataset: **`d559000`** (formerly RDA `ds559.0`).
OSDF namespace: `osdf:///ncar/gdex/d559000/…`

> ⚠️ **Note on caveats baked into the science:** CONUS404 underestimates
> mountain SWE by ~15% vs. SNOTEL, and a 4 km cell still *averages over*
> sub-grid features — it cannot see wind-scour of a single ridgeline crest.
> PropStory reports these caveats alongside every number.

---

## Install

```bash
pip install -r requirements.txt
# core: numpy, pandas, xarray, zarr
# GDEX/OSDF streaming: pelicanfs   (the 'osdf://' fsspec backend)
# nicer point selection: pyproj    (optional)
```

## Use

```bash
# Full data-driven propstory for an address (needs network + GDEX/OSDF reachable)
python -m propstory analyze --address "564 Ridge Drive, Kremmling, CO 80459" \
    --out reports/564-ridge-drive-kremmling.md

# Skip geocoding by passing coordinates directly
python -m propstory analyze --lat 40.0586 --lon -106.3884 --label "564 Ridge Dr" \
    --out reports/ridge.md

# See exactly what would be fetched, without touching the network
python -m propstory analyze --address "564 Ridge Drive, Kremmling, CO" --dry-run

# Validate the full pipeline offline on a synthetic CONUS404-like cube
python -m propstory demo --out reports/_demo.md
```

### Backends

| `--backend` | Source | Notes |
|---|---|---|
| `osdf` (default) | GDEX `d559000` via OSDF/PelicanFS | What the user asked for. Confirm the exact zarr leaf against the GDEX catalog. |
| `hytest` | HyTEST intake catalog (CONUS404 on OSN/AWS) | Same data, well-published zarr paths; a verified fallback. |

## What you get

A markdown report with, per the located grid cell:

- **Snow:** mean/median annual snowfall, peak SWE and its typical date, the
  spread between the best and worst years on record.
- **Skiable base:** days per season with ≥12" snow depth, season start/end,
  and how reliable that is year to year (the actual investment question).
- **Wind:** mean and peak winds, count of high-wind days, by season.
- **Trend:** linear change per decade in snowfall, peak SWE, and skiable days.
- **Provenance:** dataset id, grid cell lat/lon and distance from the address,
  variables, and the science caveats above.

## Layout

```
propstory/
  geocode.py      address -> lat/lon (+ elevation)
  conus404.py     open CONUS404 from GDEX/OSDF (or HyTEST); nearest-cell select
  climatology.py  point time series -> historical metrics
  report.py       metrics -> markdown propstory
  cli.py          `analyze`, `demo`, `--dry-run`
reports/          generated propstories
```
