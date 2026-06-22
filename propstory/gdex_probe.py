"""GDEX probe v8 — ARCO chunk shape + point-read timing (responsiveness gate).

For an in-browser app to feel fast, a single-point time series must map to few
chunks. This prints each ERA5 surface variable's chunk shape / array shape and
times reading the property point for (a) one year and (b) the full record, so we
know how many chunk GETs a browser would make and how long it takes.
"""

from __future__ import annotations

import time

from pelicanfs.core import PelicanFileSystem, PelicanMap
import xarray as xr

HTTPS = "https://osdf-data.gdex.ucar.edu"
SFC = "/ncar/gdex/d633000/e5.oper.an.sfc.zarr"
LAT, LON = 40.06, -106.39 % 360
VARS = ["sd", "2t", "10u", "10v", "rsn"]


def log(*a):
    print(*a, flush=True)


def main():
    log("=" * 60)
    log("GDEX PROBE v8 — ARCO chunking + point-read timing")
    log("=" * 60)
    f = PelicanFileSystem(HTTPS)
    for v in VARS:
        store = f"{SFC}/e5.oper.an.sfc.{v}.zarr"
        try:
            ds = xr.open_dataset(PelicanMap(store, pelfs=f), engine="zarr",
                                 consolidated=True)
            name = list(ds.data_vars)[0]
            da = ds[name]
            chunks = da.encoding.get("chunks")
            ntime = ds.sizes.get("time")
            tchunk = chunks[0] if chunks else None
            n_point_chunks = (ntime / tchunk) if tchunk else float("nan")
            log(f"\n{v} [{name}] shape={da.shape} dtype={da.dtype}")
            log(f"   chunks={chunks}  -> point time-series ≈ {n_point_chunks:.0f} chunk GETs")
            pt = da.sel(latitude=40.06, longitude=LON, method="nearest")
            # time a 1-year read
            t0 = time.time()
            _ = pt.sel(time=slice("2020-01-01", "2020-12-31")).load()
            log(f"   1-year point load: {time.time()-t0:.2f}s")
            # time a full-record read (daily subsample to bound memory but still
            # touches every time chunk)
            t0 = time.time()
            full = pt.load()
            log(f"   FULL-record point load ({pt.sizes.get('time')} steps): "
                f"{time.time()-t0:.1f}s  size={full.nbytes/1e6:.1f}MB")
        except Exception as e:  # noqa: BLE001
            log(f"{v}: FAIL {type(e).__name__}: {str(e)[:140]}")
    log("\nPROBE v8 COMPLETE")


if __name__ == "__main__":
    main()
