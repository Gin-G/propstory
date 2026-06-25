"""CONUS404 (d559000) feasibility probe — can we cheaply read a 4 km point series?

CONUS404 is 4 km hourly WRF, stored as hourly NetCDF + kerchunk virtual-zarr
references. Point-read cost depends on whether the NetCDF variables are
HDF5-chunked spatially (cheap point reads) or contiguous (whole-field per read).
This measures: (1) the chunk shape of a single wrf2d file, and (2) the time to
read the property point for a bounded window via the water-year kerchunk.
"""

from __future__ import annotations

import time
import traceback

from . import gdex

LAT, LON = 40.06, -106.39


def log(*a):
    print(*a, flush=True)


def probe_single_nc():
    log("=" * 64); log("CONUS404 single hourly NetCDF — variable chunking"); log("-" * 64)
    url = ("https://osdf-data.gdex.ucar.edu/ncar/gdex/d559000/wy2024/202401/"
           "wrf2d_d01_2024-01-15_18:00:00.nc")
    try:
        ds = gdex.open_conus404_nc(url)
        for v in ("SNOW", "SNOWH", "T2", "U10", "V10", "PREC_ACC_NC"):
            if v in ds.data_vars:
                log(f"  {v}: shape={ds[v].shape} chunks={ds[v].encoding.get('chunks')} "
                    f"dtype={ds[v].dtype}")
        log("  -> contiguous chunks (==shape) mean every point read pulls the whole "
            "4km field; small chunks mean cheap point reads.")
    except Exception as e:  # noqa: BLE001
        log(f"  FAIL {type(e).__name__}: {str(e)[:160]}"); traceback.print_exc()


def probe_kerchunk():
    log("=" * 64); log("CONUS404 water-year kerchunk — point read timing"); log("-" * 64)
    try:
        import numpy as np
        t0 = time.time()
        ds = gdex.open_conus404_year(2024, "2d")
        log(f"  opened wy2024 2d kerchunk in {time.time()-t0:.1f}s; dims={dict(ds.sizes)}")
        var = next((v for v in ("SNOWH", "SNOW", "T2") if v in ds.data_vars), None)
        log(f"  using var={var}; vars(sample)={list(ds.data_vars)[:10]}")
        latn = next(c for c in ("XLAT", "XLAT_M", "lat") if c in ds)
        lonn = next(c for c in ("XLONG", "XLONG_M", "lon") if c in ds)
        iy, ix, gla, glo = gdex.nearest_curvilinear(ds[latn].values, ds[lonn].values, LAT, LON)
        log(f"  nearest 4km cell ({gla:.3f},{glo:.3f}) idx=({iy},{ix})")
        tdim = next(d for d in ("Time", "time", "valid_time") if d in ds[var].dims)
        ydim, xdim = ds[var].dims[-2], ds[var].dims[-1]
        pt = ds[var].isel({ydim: iy, xdim: ix})
        log(f"  time steps in year: {ds.sizes.get(tdim)}")
        # daily-ish: every 24th step for January (~31 reads)
        t0 = time.time()
        jan = pt.isel({tdim: slice(0, 744, 24)}).load()
        log(f"  Jan daily ({jan.sizes.get(tdim)} steps): {time.time()-t0:.1f}s")
        t0 = time.time()
        janh = pt.isel({tdim: slice(0, 168)}).load()   # first week hourly
        log(f"  first-week hourly ({janh.sizes.get(tdim)} steps): {time.time()-t0:.1f}s")
        log(f"  sample {var}: {np.asarray(janh.values).ravel()[:3]}")
    except Exception as e:  # noqa: BLE001
        log(f"  FAIL {type(e).__name__}: {str(e)[:200]}"); traceback.print_exc()


def main():
    log("CONUS404 FEASIBILITY PROBE")
    probe_single_nc()
    probe_kerchunk()
    log("PROBE COMPLETE")


if __name__ == "__main__":
    main()
