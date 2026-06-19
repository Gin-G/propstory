# PropStory — Demo Ridge (synthetic)

> 🧪 **SYNTHETIC DEMO** — figures below come from a fabricated data cube to exercise the pipeline. Not real CONUS404 output.

**Historical representation from analysis-ready data — CONUS404 via NSF NCAR GDEX (`d559000`).**

## Location & data provenance

- **Address / point:** Demo Ridge (synthetic) (`40.06000, -106.39000`, ~7546 ft)
- **Matched grid cell:** `40.06000, -106.39000` (0.0 km from the point)
- **Dataset:** CONUS404 (NCAR/USGS, 4 km, hourly), GDEX `d559000`
- **Record analysed:** water years 1980–1983 (4 full years)

## Headline

| Question | Answer (this grid cell, long-term) |
|---|---|
| Does it snow? | **195 in/yr** mean annual snowfall (193 in–199 in range) |
| Does a base build? | peak SWE **5.6 in** (best year 5.7 in) |
| Is it *skiable*? | **121 days/yr** with ≥12" depth (worst year 119, best 123) |
| Is it windy? | mean **8.9 mph**, **0 windy days/yr** ≥15 mph |

## Skiable-base reliability (the investment question)

- Mean **121** skiable days/yr, std **2** (year-to-year swing 2% of the mean).
- Worst year on record: **119 days**. Best: **123 days**.
- Trend: ↑ +6.0 days/decade.
- Snowfall trend: ↑ +2.1 in/decade; peak-SWE trend: ↓ -0.5 in/decade.

## Mean snow depth by month (in)

| Oct | Nov | Dec | Jan | Feb | Mar | Apr | May | Jun |
|---|---|---|---|---|---|---|---|---|
| 3.9 | 11.9 | 18.6 | 21.1 | 18.7 | 12.0 | 3.7 | 2.5 | 2.4 |

## Year-by-year

| WY | Snowfall (in) | Peak SWE (in) | Peak date | Skiable days | Mean wind (mph) |
|---:|---:|---:|---|---:|---:|
| 1980 | 193 | 5.7 | 1980-01-13 | 120 | 8.9 |
| 1981 | 196 | 5.6 | 1981-01-09 | 122 | 8.9 |
| 1982 | 199 | 5.6 | 1982-01-20 | 119 | 8.9 |
| 1983 | 193 | 5.5 | 1983-01-19 | 123 | 8.9 |

## Caveats

- Source: CONUS404 (NCAR/USGS 4 km hydroclimate reanalysis) via NSF NCAR GDEX.
- CONUS404 underestimates mountain SWE by ~15% vs. SNOTEL; treat snow numbers as conservative.
- A 4 km grid cell averages over sub-grid terrain and cannot resolve wind-scour of a single ridge crest.
- 'Skiable day' = snow depth >= 12 in; 'windy day' = daily-mean wind >= 15 mph.
