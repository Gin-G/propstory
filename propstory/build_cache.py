"""Precompute a compact, point-optimized cache for the front end (GDEX-sourced).

Reads ERA5 surface variables for ONE grid cell from GDEX (slow, but done here in
CI, not in the user's browser), aggregates hourly -> daily, computes a climate
summary, and writes a small JSON the front end can fetch in a single request:

    web/data/<lat>_<lon>.json      (snapped to the 0.25-deg ERA5 grid)
    web/data/index.json            (list of available cells)

This is the answer to "what format makes it fast to read": time-aggregated,
point-local, one-file-per-cell. Env: PROP_LAT, PROP_LON, START_WY, END_WY.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd

from . import gdex

LAT = float(os.environ.get("PROP_LAT", "40.06"))
LON = float(os.environ.get("PROP_LON", "-106.39"))
START_WY = int(os.environ.get("START_WY", "2021"))
END_WY = int(os.environ.get("END_WY", "2025"))
OUT = os.environ.get("OUT_DIR", "web/data")

MM_PER_IN = 25.4
M_TO_IN = 39.3700787
MS_TO_MPH = 2.2369363
SKIABLE_IN = 12.0
SNOW_ON_GROUND_IN = 2.0
HIGH_WIND_MPH = 15.0


def log(m):
    print(m, flush=True)


def snap_key(lat, lon):
    """Snap to the 0.25-deg ERA5 grid; key matches the front end's snapping."""
    la = round(lat / 0.25) * 0.25
    lo = round(lon / 0.25) * 0.25
    if lo > 180:
        lo -= 360
    return f"{la:.2f}_{lo:.2f}", la, lo


def daily_for_year(stores, wy):
    start, end = f"{wy-1}-10-01", f"{wy}-09-30T23"
    cols = {}
    for k, da in stores.items():
        s = gdex.retry(lambda da=da: da.sel(time=slice(start, end)).load(),
                       label=f"{k} wy{wy}").to_series()
        cols[k] = s
    df = pd.DataFrame(cols)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index)
    rho = df["snow_density"].where(df["snow_density"] > 0)
    out = pd.DataFrame({
        "swe_in": (df["snow_depth_we"] * 1000 / MM_PER_IN).resample("1D").max(),
        "depth_in": ((df["snow_depth_we"] * 1000 / rho) * M_TO_IN).resample("1D").max().fillna(0).clip(lower=0),
        "t2f_mean": ((df["t2"] - 273.15) * 9 / 5 + 32).resample("1D").mean(),
        "t2f_min": ((df["t2"] - 273.15) * 9 / 5 + 32).resample("1D").min(),
        "t2f_max": ((df["t2"] - 273.15) * 9 / 5 + 32).resample("1D").max(),
        "wind_mean_mph": (np.hypot(df["u10"], df["v10"]) * MS_TO_MPH).resample("1D").mean(),
        "wind_max_mph": (np.hypot(df["u10"], df["v10"]) * MS_TO_MPH).resample("1D").max(),
    })
    out["wy"] = wy
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    key, glat, glon = snap_key(LAT, LON)
    log(f"cache cell {key} for property {LAT},{LON}  WY{START_WY}-{END_WY}")

    stores = {k: gdex.era5_point(LAT, LON, [k])[k]
              for k in ("snow_depth_we", "snow_density", "t2", "u10", "v10")}
    gl = float(stores["snow_depth_we"].latitude)
    go = float(stores["snow_depth_we"].longitude); go = go - 360 if go > 180 else go
    log(f"grid cell {gl:.3f},{go:.3f}")
    for k, da in stores.items():
        log(f"  {k}: chunks={da.encoding.get('chunks')} shape={da.shape} units={da.attrs.get('gdex_units')}")

    frames = []
    for wy in range(START_WY, END_WY + 1):
        t0 = time.time()
        try:
            frames.append(daily_for_year(stores, wy))
            log(f"  WY{wy} ok ({time.time()-t0:.1f}s)")
        except Exception as e:  # noqa: BLE001
            log(f"  WY{wy} FAIL {type(e).__name__}: {str(e)[:90]}")
    daily = pd.concat(frames).sort_index()
    daily = daily[~daily.index.duplicated()]
    counts = daily.groupby("wy").size()
    daily = daily[daily["wy"].isin(counts[counts >= 300].index)]

    def _d(idx):
        return None if idx is None or pd.isna(idx) else pd.Timestamp(idx).date().isoformat()

    # per water year
    by_year = []
    for wy, g in daily.groupby("wy"):
        og = g.index[g["depth_in"] >= SNOW_ON_GROUND_IN]
        by_year.append(dict(
            wy=int(wy),
            peak_swe_in=round(float(g["swe_in"].max()), 2),
            peak_swe_date=_d(g["swe_in"].idxmax()),
            peak_depth_in=round(float(g["depth_in"].max()), 1),
            skiable_days=int((g["depth_in"] >= SKIABLE_IN).sum()),
            snow_days=int((g["depth_in"] >= SNOW_ON_GROUND_IN).sum()),
            season_start=_d(og[0]) if len(og) else None,
            season_end=_d(og[-1]) if len(og) else None,
            mean_wind_mph=round(float(g["wind_mean_mph"].mean()), 1),
            windy_days=int((g["wind_mean_mph"] >= HIGH_WIND_MPH).sum()),
            coldest_f=round(float(g["t2f_min"].min()), 1),
            warmest_f=round(float(g["t2f_max"].max()), 1),
        ))

    # monthly climatology
    clim = {}
    for col, agg in (("depth_in", "mean"), ("swe_in", "mean"),
                     ("wind_mean_mph", "mean"), ("t2f_mean", "mean")):
        s = getattr(daily.groupby(daily.index.month)[col], agg)().reindex(range(1, 13))
        clim[col] = [None if pd.isna(x) else round(float(x), 2) for x in s.values]

    records = dict(
        deepest_swe={"value_in": round(float(daily["swe_in"].max()), 2), "when": _d(daily["swe_in"].idxmax())},
        windiest_day={"value_mph": round(float(daily["wind_mean_mph"].max()), 1), "when": _d(daily["wind_mean_mph"].idxmax())},
        coldest={"value_f": round(float(daily["t2f_min"].min()), 1), "when": _d(daily["t2f_min"].idxmin())},
        warmest={"value_f": round(float(daily["t2f_max"].max()), 1), "when": _d(daily["t2f_max"].idxmax())},
    )
    yrs = [r["wy"] for r in by_year]
    means = dict(
        peak_swe_in=round(float(np.mean([r["peak_swe_in"] for r in by_year])), 2),
        skiable_days=round(float(np.mean([r["skiable_days"] for r in by_year])), 1),
        mean_wind_mph=round(float(np.mean([r["mean_wind_mph"] for r in by_year])), 1),
        snow_days=round(float(np.mean([r["snow_days"] for r in by_year])), 1),
    )

    # daily series (compact: ISO date + rounded values) for the chart
    series = dict(
        t=[d.date().isoformat() for d in daily.index],
        swe_in=[round(float(x), 2) for x in daily["swe_in"].values],
        depth_in=[round(float(x), 1) for x in daily["depth_in"].values],
        wind_mph=[round(float(x), 1) for x in daily["wind_mean_mph"].values],
        t2f=[round(float(x), 1) for x in daily["t2f_mean"].values],
    )

    payload = dict(
        schema="propstory/era5-cell/v1",
        dataset="GDEX d633000 ERA5 (0.25deg hourly -> daily)",
        property={"lat": LAT, "lon": LON},
        grid_cell={"lat": round(gl, 3), "lon": round(go, 3)},
        water_years=[min(yrs), max(yrs)], n_years=len(yrs),
        means=means, records=records, monthly_climatology=clim,
        by_year=by_year, daily=series,
    )
    path = f"{OUT}/{key}.json"
    with open(path, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    sz = os.path.getsize(path) / 1024
    log(f"wrote {path} ({sz:.0f} KB)")

    # update index
    idx_path = f"{OUT}/index.json"
    idx = {}
    if os.path.exists(idx_path):
        idx = json.load(open(idx_path))
    idx[key] = {"grid_lat": round(gl, 3), "grid_lon": round(go, 3),
                "water_years": payload["water_years"]}
    json.dump(idx, open(idx_path, "w"), indent=2)
    log(f"index now has {len(idx)} cell(s)")


if __name__ == "__main__":
    main()
