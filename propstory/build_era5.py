"""Build the ERA5 propstory for the property from GDEX (artifacts only).

Pulls the ERA5 surface point series (snow depth, density, 2 m temp, 10 m winds)
from GDEX d633000, computes a multi-decade climatology with min/max-and-when
tables, and writes plots + CSV + a markdown summary into OUT_DIR.

Env knobs:  PROP_LAT, PROP_LON, START_WY, END_WY, OUT_DIR
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import gdex

LAT = float(os.environ.get("PROP_LAT", "40.06"))
LON = float(os.environ.get("PROP_LON", "-106.39"))
START_WY = int(os.environ.get("START_WY", "1991"))
END_WY = int(os.environ.get("END_WY", "2025"))
OUT = os.environ.get("OUT_DIR", "artifacts")

MM_PER_IN = 25.4
M_TO_IN = 39.3700787
MS_TO_MPH = 2.2369363
SKIABLE_IN = 12.0
SNOW_ON_GROUND_IN = 2.0
HIGH_WIND_MPH = 15.0


def log(m):
    print(m, flush=True)


def water_year(times):
    t = pd.DatetimeIndex(times)
    return t.year + (t.month >= 10).astype(int)


def daily_from_year(stores, wy):
    """Load the property point for one water year and return a daily DataFrame."""
    start = f"{wy-1}-10-01"
    end = f"{wy}-09-30T23"
    cols = {}
    for logical, da in stores.items():
        sub = gdex.retry(lambda da=da: da.sel(time=slice(start, end)).load(),
                         label=f"{logical} wy{wy}")
        cols[logical] = sub.to_series()
    df = pd.DataFrame(cols)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index)
    swe_in = df["snow_depth_we"] * 1000.0 / MM_PER_IN          # m w.e. -> mm -> in
    rho = df["snow_density"].where(df["snow_density"] > 0)
    depth_in = (df["snow_depth_we"] * 1000.0 / rho) * M_TO_IN  # physical depth in
    wind_mph = np.hypot(df["u10"], df["v10"]) * MS_TO_MPH
    t2_c = df["t2"] - 273.15
    daily = pd.DataFrame({
        "swe_in": swe_in.resample("1D").max(),
        "depth_in": depth_in.resample("1D").max().fillna(0).clip(lower=0),
        "t2_c_mean": t2_c.resample("1D").mean(),
        "t2_c_min": t2_c.resample("1D").min(),
        "t2_c_max": t2_c.resample("1D").max(),
        "wind_mean_mph": wind_mph.resample("1D").mean(),
        "wind_max_mph": wind_mph.resample("1D").max(),
    })
    daily["wy"] = wy
    return daily


def main():
    os.makedirs(OUT, exist_ok=True)
    log(f"ERA5 propstory @ {LAT},{LON}  WY{START_WY}-{END_WY}")

    stores = {lg: gdex.era5_point(LAT, LON, [lg])[lg]
              for lg in ("snow_depth_we", "snow_density", "t2", "u10", "v10")}
    glat = float(stores["snow_depth_we"].latitude)
    glon = float(stores["snow_depth_we"].longitude)
    glon = glon - 360 if glon > 180 else glon
    log(f"grid cell: {glat:.3f}, {glon:.3f}")
    for lg, da in stores.items():
        log(f"  {lg}: chunks={da.encoding.get('chunks')} units={da.attrs.get('gdex_units')}")

    # timing guard on one year -> adapt the span to a time budget
    t0 = time.time()
    first = daily_from_year(stores, END_WY - 1)
    dt = time.time() - t0
    log(f"one-year load: {dt:.1f}s ({len(first)} days)")
    budget = float(os.environ.get("YEAR_BUDGET_S", "700"))
    max_years = max(10, int(budget / max(dt, 1.0)))
    eff_start = max(START_WY, END_WY - max_years)
    log(f"effective span: WY{eff_start}-{END_WY} (budget {budget:.0f}s)")

    frames = [first]
    for wy in range(eff_start, END_WY + 1):
        if wy == END_WY - 1:
            continue
        try:
            frames.append(daily_from_year(stores, wy))
            log(f"  WY{wy} ok")
        except Exception as e:  # noqa: BLE001
            log(f"  WY{wy} FAILED {type(e).__name__}: {str(e)[:90]}")
    daily = pd.concat(frames).sort_index()
    daily = daily[~daily.index.duplicated()]
    counts = daily.groupby("wy").size()
    daily = daily[daily["wy"].isin(counts[counts >= 300].index)]
    daily.to_csv(f"{OUT}/era5_point_daily.csv")

    # ---- per water-year stats ----
    def _date(idx):
        return None if idx is None or pd.isna(idx) else pd.Timestamp(idx).date().isoformat()

    rows = []
    for wy, g in daily.groupby("wy"):
        og = g.index[g["depth_in"] >= SNOW_ON_GROUND_IN]
        rows.append(dict(
            wy=int(wy),
            peak_swe_in=float(g["swe_in"].max()),
            peak_swe_date=_date(g["swe_in"].idxmax()),
            peak_depth_in=float(g["depth_in"].max()),
            skiable_days=int((g["depth_in"] >= SKIABLE_IN).sum()),
            snow_days=int((g["depth_in"] >= SNOW_ON_GROUND_IN).sum()),
            season_start=_date(og[0]) if len(og) else None,
            season_end=_date(og[-1]) if len(og) else None,
            mean_wind_mph=float(g["wind_mean_mph"].mean()),
            windy_days=int((g["wind_mean_mph"] >= HIGH_WIND_MPH).sum()),
            coldest_c=float(g["t2_c_min"].min()),
            warmest_c=float(g["t2_c_max"].max()),
        ))
    yr = pd.DataFrame(rows).set_index("wy")
    yr.to_csv(f"{OUT}/era5_by_water_year.csv")

    def trend(s):
        x = np.asarray(s.index, float); y = np.asarray(s.values, float)
        ok = np.isfinite(y)
        return float(np.polyfit(x[ok], y[ok], 1)[0] * 10) if ok.sum() > 2 else float("nan")

    # ---- record extremes with dates ----
    ext = dict(
        deepest_swe=dict(value_in=round(float(daily["swe_in"].max()), 2),
                         when=_date(daily["swe_in"].idxmax())),
        windiest_day=dict(value_mph=round(float(daily["wind_mean_mph"].max()), 1),
                          when=_date(daily["wind_mean_mph"].idxmax())),
        peak_gust_hourlyish=dict(value_mph=round(float(daily["wind_max_mph"].max()), 1),
                                 when=_date(daily["wind_max_mph"].idxmax())),
        coldest=dict(value_c=round(float(daily["t2_c_min"].min()), 1),
                     when=_date(daily["t2_c_min"].idxmin())),
        warmest=dict(value_c=round(float(daily["t2_c_max"].max()), 1),
                     when=_date(daily["t2_c_max"].idxmax())),
        longest_season=dict(days=int(yr["snow_days"].max()),
                            water_year=int(yr["snow_days"].idxmax())),
        most_skiable=dict(days=int(yr["skiable_days"].max()),
                          water_year=int(yr["skiable_days"].idxmax())),
        least_skiable=dict(days=int(yr["skiable_days"].min()),
                           water_year=int(yr["skiable_days"].idxmin())),
    )
    metrics = dict(
        property=dict(lat=LAT, lon=LON), grid_cell=dict(lat=glat, lon=glon),
        dataset="GDEX d633000 ERA5 (0.25deg hourly)",
        water_years=[int(yr.index.min()), int(yr.index.max())], n_years=int(len(yr)),
        means={c: round(float(yr[c].mean()), 2) for c in
               ["peak_swe_in", "peak_depth_in", "skiable_days", "snow_days",
                "mean_wind_mph", "windy_days"]},
        trends_per_decade=dict(peak_swe_in=round(trend(yr["peak_swe_in"]), 2),
                               skiable_days=round(trend(yr["skiable_days"]), 2)),
        extremes=ext,
    )
    with open(f"{OUT}/era5_metrics.json", "w") as fh:
        json.dump(metrics, fh, indent=2)

    _plots(daily, yr, glat, glon)
    _summary(metrics, yr)
    log("DONE -> " + OUT)
    log(json.dumps(metrics, indent=2))


def _plots(daily, yr, glat, glon):
    plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": .3,
                         "axes.axisbelow": True, "font.size": 10})
    # 1 daily SWE
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.fill_between(daily.index, daily["swe_in"], color="#3b78b0", lw=0)
    ax.set_ylabel("snow water equiv (in)")
    ax.set_title(f"ERA5 daily snow (SWE) — {glat:.2f}N {glon:.2f}W (GDEX d633000)")
    fig.tight_layout(); fig.savefig(f"{OUT}/01_swe_daily.png"); plt.close(fig)
    # 2 annual peak SWE + skiable days
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.bar(yr.index, yr["peak_swe_in"], color="#5b9bd5", label="peak SWE (in)")
    ax.axhline(yr["peak_swe_in"].mean(), color="#333", ls=":",
               label=f"mean {yr['peak_swe_in'].mean():.1f}\"")
    ax2 = ax.twinx()
    ax2.plot(yr.index, yr["skiable_days"], color="#c0392b", marker="o", lw=1.4,
             label="skiable days")
    ax.set_xlabel("water year"); ax.set_ylabel("peak SWE (in)")
    ax2.set_ylabel("skiable days", color="#c0392b")
    ax.set_title("Annual peak snow & skiable days (depth ≥ 12 in)")
    ax.legend(loc="upper left"); fig.tight_layout()
    fig.savefig(f"{OUT}/02_annual_peak_skiable.png"); plt.close(fig)
    # 3 monthly climatology
    mlab = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    order = [10, 11, 12, 1, 2, 3, 4, 5, 6]
    md = daily.groupby(daily.index.month)["depth_in"].mean()
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.bar(range(len(order)), [md.get(m, 0) for m in order], color="#5b9bd5")
    ax.axhline(SKIABLE_IN, color="#c0392b", ls="--", lw=1)
    ax.set_xticks(range(len(order))); ax.set_xticklabels(mlab)
    ax.set_ylabel("mean snow depth (in)"); ax.set_title("Mean snow depth by month")
    fig.tight_layout(); fig.savefig(f"{OUT}/03_monthly_snow.png"); plt.close(fig)
    # 4 wind monthly
    wm = daily.groupby(daily.index.month)["wind_mean_mph"].mean().reindex(range(1, 13))
    wx = daily.groupby(daily.index.month)["wind_max_mph"].max().reindex(range(1, 13))
    ml = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.bar(range(12), wm.values, color="#8aa", label="mean daily wind")
    ax.plot(range(12), wx.values, color="#c0392b", marker="o", lw=1.2, label="max")
    ax.set_xticks(range(12)); ax.set_xticklabels(ml); ax.set_ylabel("wind (mph)")
    ax.set_title("10 m wind by month"); ax.legend(); fig.tight_layout()
    fig.savefig(f"{OUT}/04_wind_monthly.png"); plt.close(fig)
    # 5 temp envelope
    tg = daily.groupby(daily.index.month)
    tmin = tg["t2_c_min"].min().reindex(range(1, 13))
    tmax = tg["t2_c_max"].max().reindex(range(1, 13))
    tmean = tg["t2_c_mean"].mean().reindex(range(1, 13))
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.fill_between(range(12), tmin.values, tmax.values, color="#cdd", alpha=.6,
                    label="record min/max")
    ax.plot(range(12), tmean.values, color="#b5651d", marker="o", label="mean")
    ax.axhline(0, color="#3b78b0", ls=":", lw=1)
    ax.set_xticks(range(12)); ax.set_xticklabels(ml); ax.set_ylabel("2 m temp (°C)")
    ax.set_title("Temperature by month"); ax.legend(); fig.tight_layout()
    fig.savefig(f"{OUT}/05_temp_monthly.png"); plt.close(fig)


def _summary(m, yr):
    e = m["extremes"]
    L = ["# ERA5 propstory (GDEX d633000)", "",
         f"Property {m['property']['lat']}, {m['property']['lon']} → grid cell "
         f"{m['grid_cell']['lat']:.3f}, {m['grid_cell']['lon']:.3f}",
         f"Water years {m['water_years'][0]}–{m['water_years'][1]} ({m['n_years']})", "",
         "## Means", ""]
    for k, v in m["means"].items():
        L.append(f"- {k}: {v}")
    L += ["", "## Records (value — when)", "",
          f"- Deepest SWE: {e['deepest_swe']['value_in']} in on {e['deepest_swe']['when']}",
          f"- Windiest day: {e['windiest_day']['value_mph']} mph on {e['windiest_day']['when']}",
          f"- Coldest: {e['coldest']['value_c']} °C on {e['coldest']['when']}",
          f"- Warmest: {e['warmest']['value_c']} °C on {e['warmest']['when']}",
          f"- Most skiable days: {e['most_skiable']['days']} (WY{e['most_skiable']['water_year']})",
          f"- Least skiable days: {e['least_skiable']['days']} (WY{e['least_skiable']['water_year']})",
          "", "## Trends per decade", ""]
    for k, v in m["trends_per_decade"].items():
        L.append(f"- {k}: {v:+}")
    open(f"{OUT}/SUMMARY.md", "w").write("\n".join(L))


if __name__ == "__main__":
    main()
