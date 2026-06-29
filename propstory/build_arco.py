"""Build a point/time-optimized ("analysis-ready for time-series") ERA5 store.

This is the *real* fix for fast live in-browser point queries. GDEX's ERA5 is
area-chunked ([27, 480, 241] ≈ 12 MB/chunk), so a single point's time-series
fans out into ~1 chunk per 27 hours (≈19 GB for 5 yr) — impractical live. But
that same area-chunking makes reading a *region* cheap: every cell in a small
bbox shares the same spatial chunks, so the whole bbox costs ≈ one cell's read.

So here (in CI, once) we read a bbox, aggregate hourly→daily, and rewrite it
**time-contiguous** (chunks [all-time, 4, 4]) as a consolidated Zarr v2 under
web/arco/. The browser then reads any in-bbox cell's full daily history in a
couple of small same-origin fetches — exactly the rechunking GDEX should publish.

Env: ARCO_LAT_MIN/MAX, ARCO_LON_MIN/MAX, START_WY, END_WY, OUT_DIR.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd

from . import gdex

LAT_MIN = float(os.environ.get("ARCO_LAT_MIN", "39.0"))
LAT_MAX = float(os.environ.get("ARCO_LAT_MAX", "41.0"))
LON_MIN = float(os.environ.get("ARCO_LON_MIN", "-107.0"))
LON_MAX = float(os.environ.get("ARCO_LON_MAX", "-105.0"))
START_WY = int(os.environ.get("START_WY", "2021"))
END_WY = int(os.environ.get("END_WY", "2025"))
OUT = os.environ.get("OUT_DIR", "web/arco")
STORE = "era5_co_daily.zarr"

MM_PER_IN = 25.4
MS_TO_MPH = 2.2369363


def log(m):
    print(m, flush=True)


def _bbox(da):
    """Select the bbox; ERA5 latitude is descending and longitude is 0..360."""
    lon_is_360 = float(da["longitude"].max()) > 180
    lo0, lo1 = (LON_MIN % 360, LON_MAX % 360) if lon_is_360 else (LON_MIN, LON_MAX)
    return da.sel(latitude=slice(LAT_MAX, LAT_MIN), longitude=slice(lo0, lo1))


def main():
    os.makedirs(OUT, exist_ok=True)
    start, end = f"{START_WY-1}-10-01", f"{END_WY}-09-30T23"
    log(f"ARCO build bbox lat[{LAT_MIN},{LAT_MAX}] lon[{LON_MIN},{LON_MAX}] "
        f"time {start}..{end}")

    fields = {}
    for code in ("sd", "2t", "10u", "10v"):
        ds = gdex.open_era5_var(code)
        var = list(ds.data_vars)[0]
        da = _bbox(ds[var]).sel(time=slice(start, end))
        log(f"  {code}: loading {da.shape} (area-chunked → shared chunks) …")
        t0 = time.time()
        fields[code] = gdex.retry(lambda da=da: da.load(), label=f"load {code}")
        log(f"    {code} loaded in {time.time()-t0:.1f}s")

    sd, t2, u10, v10 = fields["sd"], fields["2t"], fields["10u"], fields["10v"]
    swe_in = (sd * 1000.0 / MM_PER_IN)
    t2f = (t2 - 273.15) * 9 / 5 + 32
    wind = np.hypot(u10, v10) * MS_TO_MPH

    # hourly → daily per cell (vectorised over the whole bbox)
    daily = (
        __import__("xarray").Dataset({
            "swe_in": swe_in.resample(time="1D").max(),
            "t2f_min": t2f.resample(time="1D").min(),
            "t2f_mean": t2f.resample(time="1D").mean(),
            "t2f_max": t2f.resample(time="1D").max(),
            "wind_mph": wind.resample(time="1D").mean(),
        })
        .round(2)
    )
    # normalise longitude to -180..180 for the browser
    lon = daily["longitude"].values
    daily = daily.assign_coords(longitude=np.where(lon > 180, lon - 360, lon))

    nt = daily.sizes["time"]
    nlat = daily.sizes["latitude"]
    nlon = daily.sizes["longitude"]
    log(f"daily grid: time={nt} lat={nlat} lon={nlon}")

    # time-contiguous chunks: a single cell's full history is one small chunk
    enc = {v: {"chunks": (nt, min(4, nlat), min(4, nlon))} for v in daily.data_vars}
    path = f"{OUT}/{STORE}"
    if os.path.exists(path):
        import shutil
        shutil.rmtree(path)
    daily.to_zarr(path, mode="w", consolidated=True, zarr_format=2, encoding=enc)
    log(f"wrote {path}")

    idx = {
        "schema": "propstory/era5-arco/v1",
        "dataset": "GDEX d633000 ERA5 → daily, time-contiguous rechunk",
        "store": STORE,
        "bbox": {"lat_min": LAT_MIN, "lat_max": LAT_MAX,
                 "lon_min": LON_MIN, "lon_max": LON_MAX},
        "grid_deg": 0.25,
        "water_years": [START_WY, END_WY],
        "vars": list(daily.data_vars),
        "time_start": pd.Timestamp(daily["time"].values[0]).date().isoformat(),
        "n_time": int(nt),
        "lat": [round(float(x), 3) for x in daily["latitude"].values],
        "lon": [round(float(x), 3) for x in daily["longitude"].values],
    }
    with open(f"{OUT}/index.json", "w") as fh:
        json.dump(idx, fh, indent=2)
    log(f"wrote {OUT}/index.json ({nlat}x{nlon} cells, {len(idx['vars'])} vars)")


if __name__ == "__main__":
    main()
