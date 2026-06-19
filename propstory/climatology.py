"""Turn a CONUS404 point time series into the historical metrics that make up a
propstory: snowfall, skiable-base reliability, wind, and their trends.

All public functions operate on an :class:`xarray.Dataset` already sliced to a
single grid cell (see :func:`propstory.conus404.point_timeseries`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MM_PER_IN = 25.4
M_TO_IN = 39.3700787
MS_TO_MPH = 2.2369363
SKIABLE_DEPTH_IN = 12.0        # a usable backyard base
HIGH_WIND_MPH = 15.0           # daily-mean threshold for a "windy day"


@dataclass
class YearStats:
    water_year: int
    total_precip_in: float
    total_snowfall_in: float
    peak_swe_in: float
    peak_swe_date: str | None
    skiable_days: int
    season_start: str | None
    season_end: str | None
    mean_wind_mph: float
    max_wind_mph: float
    high_wind_days: int


@dataclass
class Climatology:
    n_years: int
    first_water_year: int
    last_water_year: int
    per_year: list[YearStats] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    monthly_snow_depth_in: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _to_daily(pt, variables: dict[str, str]) -> pd.DataFrame:
    """Collapse the hourly point series to a tidy daily DataFrame."""
    cols = {}
    if "swe" in variables:
        cols["swe_in"] = pt[variables["swe"]] / MM_PER_IN          # mm -> in
    if "snow_depth" in variables:
        cols["depth_in"] = pt[variables["snow_depth"]] * M_TO_IN   # m  -> in
    if "precip" in variables:
        cols["precip_in"] = pt[variables["precip"]] / MM_PER_IN    # mm -> in
    if "snowfall" in variables:
        cols["snowfall_in"] = pt[variables["snowfall"]] / MM_PER_IN
    if "t2" in variables:
        cols["t2_c"] = pt[variables["t2"]] - 273.15
    if "u10" in variables and "v10" in variables:
        spd = np.hypot(pt[variables["u10"]], pt[variables["v10"]]) * MS_TO_MPH
        cols["wind_mph"] = spd

    frame = {}
    for name, da in cols.items():
        s = da.to_series()
        frame[name] = s
    df = pd.DataFrame(frame)
    df.index = pd.to_datetime(df.index)

    agg = {}
    if "swe_in" in df:
        agg["swe_in"] = ("swe_in", "max")
    if "depth_in" in df:
        agg["depth_in"] = ("depth_in", "max")
    if "precip_in" in df:
        agg["precip_in"] = ("precip_in", "sum")
    if "snowfall_in" in df:
        agg["snowfall_in"] = ("snowfall_in", "sum")
    if "t2_c" in df:
        agg["t2_c"] = ("t2_c", "mean")
    if "wind_mph" in df:
        agg["wind_mean_mph"] = ("wind_mph", "mean")
        agg["wind_max_mph"] = ("wind_mph", "max")

    daily = df.resample("1D").agg(**agg)
    # Water year (Oct-Sep) labelled by the calendar year it ends in.
    daily["wy"] = daily.index.year + (daily.index.month >= 10).astype(int)
    return daily


def _snowfall_from_accum(daily: pd.DataFrame) -> pd.Series:
    """ACSNOW is a since-start accumulation bucket; recover per-day snowfall."""
    if "snowfall_in" not in daily:
        return pd.Series(index=daily.index, dtype=float)
    diff = daily["snowfall_in"].diff()
    diff[diff < 0] = daily["snowfall_in"][diff < 0]  # bucket reset -> use raw value
    return diff.clip(lower=0)


def _year_stats(wy: int, g: pd.DataFrame, snowfall: pd.Series) -> YearStats:
    def _date(idx) -> str | None:
        return None if idx is None or pd.isna(idx) else pd.Timestamp(idx).date().isoformat()

    peak_idx = g["swe_in"].idxmax() if "swe_in" in g and g["swe_in"].notna().any() else None
    skiable = g["depth_in"] >= SKIABLE_DEPTH_IN if "depth_in" in g else pd.Series(False, index=g.index)
    skiable_days = int(skiable.sum())
    season = g.index[skiable] if skiable.any() else []

    return YearStats(
        water_year=wy,
        total_precip_in=float(g["precip_in"].sum()) if "precip_in" in g else float("nan"),
        total_snowfall_in=float(snowfall.reindex(g.index).sum()),
        peak_swe_in=float(g["swe_in"].max()) if "swe_in" in g else float("nan"),
        peak_swe_date=_date(peak_idx),
        skiable_days=skiable_days,
        season_start=_date(season[0]) if len(season) else None,
        season_end=_date(season[-1]) if len(season) else None,
        mean_wind_mph=float(g["wind_mean_mph"].mean()) if "wind_mean_mph" in g else float("nan"),
        max_wind_mph=float(g["wind_max_mph"].max()) if "wind_max_mph" in g else float("nan"),
        high_wind_days=int((g["wind_mean_mph"] >= HIGH_WIND_MPH).sum()) if "wind_mean_mph" in g else 0,
    )


def _trend_per_decade(years: list[int], values: list[float]) -> float:
    """Least-squares slope, scaled to 'per decade'. NaN-safe."""
    x = np.asarray(years, float)
    y = np.asarray(values, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return float("nan")
    slope = np.polyfit(x[ok], y[ok], 1)[0]
    return float(slope * 10.0)


def compute(pt, variables: dict[str, str]) -> Climatology:
    """Compute the full :class:`Climatology` for a point time series."""
    daily = _to_daily(pt, variables)
    snowfall = _snowfall_from_accum(daily)

    # Drop partial water years at the ends of the record for clean stats.
    counts = daily.groupby("wy").size()
    full_years = counts[counts >= 300].index
    daily = daily[daily["wy"].isin(full_years)]

    per_year = [_year_stats(int(wy), g, snowfall) for wy, g in daily.groupby("wy")]
    per_year.sort(key=lambda y: y.water_year)

    def col(attr):
        return [getattr(y, attr) for y in per_year]

    years = col("water_year")

    def stat(attr):
        v = np.asarray(col(attr), float)
        v = v[np.isfinite(v)]
        if v.size == 0:
            return {}
        return {
            "mean": float(np.mean(v)),
            "median": float(np.median(v)),
            "min": float(np.min(v)),
            "max": float(np.max(v)),
            "std": float(np.std(v, ddof=1)) if v.size > 1 else 0.0,
            "trend_per_decade": _trend_per_decade(years, col(attr)),
        }

    summary = {
        "annual_snowfall_in": stat("total_snowfall_in"),
        "annual_precip_in": stat("total_precip_in"),
        "peak_swe_in": stat("peak_swe_in"),
        "skiable_days": stat("skiable_days"),
        "mean_wind_mph": stat("mean_wind_mph"),
        "high_wind_days": stat("high_wind_days"),
    }

    monthly = {}
    if "depth_in" in daily:
        m = daily["depth_in"].groupby(daily.index.month).mean()
        monthly = {int(k): float(v) for k, v in m.items()}

    notes = [
        "Source: CONUS404 (NCAR/USGS 4 km hydroclimate reanalysis) via NSF NCAR GDEX.",
        "CONUS404 underestimates mountain SWE by ~15% vs. SNOTEL; treat snow numbers as conservative.",
        "A 4 km grid cell averages over sub-grid terrain and cannot resolve wind-scour of a single ridge crest.",
        f"'Skiable day' = snow depth >= {SKIABLE_DEPTH_IN:.0f} in; 'windy day' = daily-mean wind >= {HIGH_WIND_MPH:.0f} mph.",
    ]

    return Climatology(
        n_years=len(per_year),
        first_water_year=years[0] if years else 0,
        last_water_year=years[-1] if years else 0,
        per_year=per_year,
        summary=summary,
        monthly_snow_depth_in=monthly,
        notes=notes,
    )
