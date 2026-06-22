"""GDEX access probe v5 — prove real point extraction (GDEX-only).

Solved by v4:
  * ERA5 d633000 surface = per-variable zarr stores:
        e5.oper.an.sfc.zarr/e5.oper.an.sfc.<var>.zarr   (consolidated metadata)
    open with consolidated=True (needs dask).  Vars: 2t, 10u, 10v, sd, rsn, ...
  * CONUS404 d559000 raw = hourly NetCDF (wrf2d_d01_<date>_<HH>:00:00.nc);
    multi-time access is via kerchunk refs, but a single .nc opens directly.

v5 extracts the property point from ERA5 (snow depth, temp, wind) and from one
CONUS404 hourly file (SNOW, SNOWH, T2, U10, V10).
"""

from __future__ import annotations

import io
import time
import traceback


def retry(fn, attempts=4, base=2.0):
    """OSDF reads occasionally raise transient payload errors; retry them."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"       retry {i+1}/{attempts} after {type(e).__name__}: {str(e)[:80]}")
            time.sleep(base * (i + 1))
    raise last

LAT, LON = 40.06, -106.39
HTTPS = "https://osdf-data.gdex.ucar.edu"
NS = "/ncar/gdex"

ERA5_SFC = f"{NS}/d633000/e5.oper.an.sfc.zarr"
ERA5_VARS = {"sd": "snow depth (m of water equiv)",
             "2t": "2 m temperature (K)",
             "10u": "10 m u-wind (m/s)",
             "10v": "10 m v-wind (m/s)"}
CONUS404_NC = (f"{HTTPS}{NS}/d559000/wy2021/202101/"
               "wrf2d_d01_2021-01-15_18:00:00.nc")


def log(*a):
    print(*a, flush=True)


def line():
    log("-" * 72)


def era5():
    import xarray as xr
    from pelicanfs.core import PelicanFileSystem, PelicanMap
    log("ERA5 (d633000) PER-VARIABLE ZARR"); line()
    f = PelicanFileSystem(HTTPS)
    for v, desc in ERA5_VARS.items():
        store = f"{ERA5_SFC}/e5.oper.an.sfc.{v}.zarr"
        try:
            ds = retry(lambda: xr.open_dataset(PelicanMap(store, pelfs=f),
                                               engine="zarr", consolidated=True))
            var = list(ds.data_vars)[0]
            lo = ds["longitude"]
            lonsel = LON % 360 if float(lo.max()) > 180 else LON
            pt = ds[var].sel(latitude=LAT, longitude=lonsel, method="nearest")
            t0 = str(ds.time.values[0])[:13]; t1 = str(ds.time.values[-1])[:13]
            log(f"  {v:4s} [{var}] {desc}")
            log(f"       grid cell ({float(pt.latitude):.2f},{float(pt.longitude):.2f}) "
                f"time {t0}..{t1} n={ds.sizes.get('time')}")
            sample = retry(lambda: float(
                pt.sel(time="2021-01-15T18:00", method="nearest").values))
            log(f"       2021-01-15T18 value = {sample:.4f}  units={ds[var].attrs.get('units')}")
        except Exception as e:
            log(f"  {v}: FAIL {type(e).__name__}: {str(e)[:140]}")
    log("")


def conus404():
    import fsspec
    import numpy as np
    import xarray as xr
    log("CONUS404 (d559000) single hourly NetCDF"); line()
    log(f"  {CONUS404_NC}")
    try:
        data = retry(lambda: fsspec.open(CONUS404_NC, "rb").open().read())
        ds = xr.open_dataset(io.BytesIO(data), engine="h5netcdf")
        log(f"  opened dims={dict(ds.sizes)}")
        vars_ = [v for v in ("SNOW", "SNOWH", "T2", "U10", "V10",
                             "PREC_ACC_NC", "ACSNOW") if v in ds.data_vars]
        log(f"  surface vars present: {vars_}")
        lat = np.asarray(ds["XLAT"].values).squeeze()
        lon = np.asarray(ds["XLONG"].values).squeeze()
        d = (lat - LAT) ** 2 + (lon - LON) ** 2
        iy, ix = np.unravel_index(int(np.argmin(d)), d.shape)
        log(f"  nearest 4km cell ({float(lat[iy,ix]):.3f},{float(lon[iy,ix]):.3f})")
        for v in vars_:
            arr = np.asarray(ds[v].values).squeeze()
            log(f"    {v} = {float(arr[iy, ix]):.4f}  units={ds[v].attrs.get('units')}")
    except Exception as e:
        log(f"  FAIL {type(e).__name__}: {str(e)[:160]}")
        traceback.print_exc()
    log("")


def main():
    log("=" * 72); log("GDEX PROBE v5 — real point extraction"); log("=" * 72)
    log(f"property: {LAT}, {LON}\n")
    for step in (era5, conus404):
        try:
            step()
        except Exception:
            traceback.print_exc()
    log("PROBE v5 COMPLETE")


if __name__ == "__main__":
    main()
