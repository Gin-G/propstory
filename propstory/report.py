"""Render a :class:`~propstory.climatology.Climatology` into a markdown propstory."""

from __future__ import annotations

from .climatology import Climatology
from .conus404 import GDEX_DATASET_ID
from .geocode import Location

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt(x, unit="", nd=1):
    if x is None or x != x:  # NaN
        return "n/a"
    return f"{x:.{nd}f}{unit}"


def _trend_phrase(s: dict, unit: str) -> str:
    t = s.get("trend_per_decade")
    if t is None or t != t:
        return "trend: n/a"
    arrow = "↑" if t > 0 else ("↓" if t < 0 else "→")
    return f"{arrow} {t:+.1f}{unit}/decade"


def render(
    loc: Location,
    sel,
    clim: Climatology,
    *,
    title: str | None = None,
    synthetic: bool = False,
) -> str:
    title = title or loc.label
    s = clim.summary
    snow = s.get("annual_snowfall_in", {})
    swe = s.get("peak_swe_in", {})
    ski = s.get("skiable_days", {})
    wind = s.get("mean_wind_mph", {})
    hiwind = s.get("high_wind_days", {})

    lines: list[str] = []
    lines.append(f"# PropStory — {title}")
    lines.append("")
    if synthetic:
        lines.append("> 🧪 **SYNTHETIC DEMO** — figures below come from a fabricated "
                     "data cube to exercise the pipeline. Not real CONUS404 output.")
        lines.append("")
    lines.append(f"**Historical representation from analysis-ready data — "
                 f"CONUS404 via NSF NCAR GDEX (`{GDEX_DATASET_ID}`).**")
    lines.append("")

    # Provenance block
    elev = f", ~{loc.elevation_ft:.0f} ft" if loc.elevation_ft else ""
    lines.append("## Location & data provenance")
    lines.append("")
    lines.append(f"- **Address / point:** {loc.display_name or loc.label} "
                 f"(`{loc.lat:.5f}, {loc.lon:.5f}`{elev})")
    lines.append(f"- **Matched grid cell:** `{sel.grid_lat:.5f}, {sel.grid_lon:.5f}` "
                 f"({sel.distance_km:.1f} km from the point)")
    lines.append(f"- **Dataset:** CONUS404 (NCAR/USGS, 4 km, hourly), GDEX `{GDEX_DATASET_ID}`")
    lines.append(f"- **Record analysed:** water years {clim.first_water_year}–"
                 f"{clim.last_water_year} ({clim.n_years} full years)")
    lines.append("")

    # Headline answers
    lines.append("## Headline")
    lines.append("")
    lines.append("| Question | Answer (this grid cell, long-term) |")
    lines.append("|---|---|")
    lines.append(f"| Does it snow? | **{_fmt(snow.get('mean'),' in/yr',0)}** mean annual snowfall "
                 f"({_fmt(snow.get('min'),' in',0)}–{_fmt(snow.get('max'),' in',0)} range) |")
    lines.append(f"| Does a base build? | peak SWE **{_fmt(swe.get('mean'),' in',1)}** "
                 f"(best year {_fmt(swe.get('max'),' in',1)}) |")
    lines.append(f"| Is it *skiable*? | **{_fmt(ski.get('mean'),' days/yr',0)}** with ≥12\" depth "
                 f"(worst year {_fmt(ski.get('min'),'',0)}, best {_fmt(ski.get('max'),'',0)}) |")
    lines.append(f"| Is it windy? | mean **{_fmt(wind.get('mean'),' mph',1)}**, "
                 f"**{_fmt(hiwind.get('mean'),' windy days/yr',0)}** ≥15 mph |")
    lines.append("")

    # Reliability / investment lens
    lines.append("## Skiable-base reliability (the investment question)")
    lines.append("")
    if ski:
        cv = (ski.get("std", 0) / ski["mean"]) if ski.get("mean") else float("nan")
        lines.append(f"- Mean **{_fmt(ski.get('mean'),'',0)}** skiable days/yr, "
                     f"std **{_fmt(ski.get('std'),'',0)}** "
                     f"(year-to-year swing {_fmt(cv*100,'%',0)} of the mean).")
        lines.append(f"- Worst year on record: **{_fmt(ski.get('min'),' days',0)}**. "
                     f"Best: **{_fmt(ski.get('max'),' days',0)}**.")
        lines.append(f"- Trend: {_trend_phrase(ski, ' days')}.")
    lines.append(f"- Snowfall trend: {_trend_phrase(snow, ' in')}; "
                 f"peak-SWE trend: {_trend_phrase(swe, ' in')}.")
    lines.append("")

    # Monthly snow depth sparkline-ish table
    if clim.monthly_snow_depth_in:
        lines.append("## Mean snow depth by month (in)")
        lines.append("")
        order = [10, 11, 12, 1, 2, 3, 4, 5, 6]  # water-year order
        present = [m for m in order if m in clim.monthly_snow_depth_in]
        lines.append("| " + " | ".join(_MONTHS[m] for m in present) + " |")
        lines.append("|" + "---|" * len(present))
        lines.append("| " + " | ".join(_fmt(clim.monthly_snow_depth_in[m], "", 1)
                                        for m in present) + " |")
        lines.append("")

    # Per-year table (compact)
    lines.append("## Year-by-year")
    lines.append("")
    lines.append("| WY | Snowfall (in) | Peak SWE (in) | Peak date | Skiable days | Mean wind (mph) |")
    lines.append("|---:|---:|---:|---|---:|---:|")
    for y in clim.per_year:
        lines.append(f"| {y.water_year} | {_fmt(y.total_snowfall_in,'',0)} | "
                     f"{_fmt(y.peak_swe_in,'',1)} | {y.peak_swe_date or '—'} | "
                     f"{y.skiable_days} | {_fmt(y.mean_wind_mph,'',1)} |")
    lines.append("")

    # Caveats
    lines.append("## Caveats")
    lines.append("")
    for n in clim.notes:
        lines.append(f"- {n}")
    lines.append("")

    return "\n".join(lines)
