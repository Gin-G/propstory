"""A small synthetic CONUS404-like dataset for offline pipeline validation.

It mimics CONUS404's structure (curvilinear 2-D lat/lon, native WRF variable
names and units) on a tiny grid over a few water years so the full
geocode-free path -- nearest cell, point extraction, climatology, report -- can
be exercised without network access. The numbers are fabricated, not physical.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr


def synthetic_dataset(center=(40.06, -106.39), n=5, years=4, seed=0):
    """Build a tiny CONUS404-shaped dataset centred on ``center`` (lat, lon)."""
    rng = np.random.default_rng(seed)
    clat, clon = center

    # ~4 km spacing in degrees-ish; just enough to make nearest-cell meaningful.
    dlat = 0.036
    dlon = 0.047
    j = np.arange(n) - n // 2
    lat1d = clat + j * dlat
    lon1d = clon + j * dlon
    lon2d, lat2d = np.meshgrid(lon1d, lat1d)

    time = pd.date_range("1979-10-01", periods=years * 365 * 24, freq="h")
    doy = time.dayofyear.to_numpy()
    # Cold/snowy in winter, warm/dry in summer.
    seasonal = np.cos((doy - 15) / 365.0 * 2 * np.pi)  # +1 ~ mid-Jan

    nt = len(time)
    shape = (nt, n, n)

    t2 = 278.0 + 12.0 * seasonal[:, None, None] - 8.0 * np.cos(time.hour.to_numpy()[:, None, None] / 24 * 2 * np.pi)
    t2 = t2 + rng.normal(0, 2.0, shape)

    snowy = np.clip(seasonal, 0, None)[:, None, None]
    precip = np.clip(rng.gamma(0.3, 0.6, shape) * (0.4 + snowy), 0, None)  # mm/hr
    swe = np.clip((snowy * 120.0) + rng.normal(0, 8, shape), 0, None)       # mm
    snowh = swe / 250.0 * 1.0                                               # m (~250 kg/m3)
    acsnow = np.cumsum(precip * (t2 < 273.15), axis=0)                      # mm bucket
    u10 = rng.normal(0, 3.0, shape) + 2.0 * seasonal[:, None, None]
    v10 = rng.normal(0, 3.0, shape)

    return xr.Dataset(
        {
            "T2": (("time", "south_north", "west_east"), t2.astype("float32")),
            "PREC_ACC_NC": (("time", "south_north", "west_east"), precip.astype("float32")),
            "SNOW": (("time", "south_north", "west_east"), swe.astype("float32")),
            "SNOWH": (("time", "south_north", "west_east"), snowh.astype("float32")),
            "ACSNOW": (("time", "south_north", "west_east"), acsnow.astype("float32")),
            "U10": (("time", "south_north", "west_east"), u10.astype("float32")),
            "V10": (("time", "south_north", "west_east"), v10.astype("float32")),
        },
        coords={
            "time": time,
            "XLAT": (("south_north", "west_east"), lat2d),
            "XLONG": (("south_north", "west_east"), lon2d),
        },
    )
