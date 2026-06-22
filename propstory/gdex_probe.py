"""GDEX probe v9 — ARCO chunk shape + bounded-window point timing (fast).

Prints each ERA5 surface variable's chunk shape and times reading the property
point for 1 year and 5 years (no full-record load, so it returns quickly). This
tells us how many chunk GETs a browser makes per year of data and how snappy a
bounded live query will feel.
"""

from __future__ import annotations

import time

from pelicanfs.core import PelicanFileSystem, PelicanMap
import xarray as xr

HTTPS = "https://osdf-data.gdex.ucar.edu"
SFC = "/ncar/gdex/d633000/e5.oper.an.sfc.zarr"
LONsel = -106.39 % 360
VARS = ["sd", "2t", "10u", "10v", "rsn"]


def log(*a):
    print(*a, flush=True)


def main():
    log("=" * 60)
    log("GDEX PROBE v9 — chunking + bounded point timing")
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
            per_year = (8766 / tchunk) if tchunk else float("nan")
            log(f"\n{v} [{name}] shape={da.shape} dtype={da.dtype} ntime={ntime}")
            log(f"   chunks={chunks}  -> ~{per_year:.1f} time-chunks per year")
            pt = da.sel(latitude=40.06, longitude=LONsel, method="nearest")
            t0 = time.time()
            one = pt.sel(time=slice("2020-01-01", "2020-12-31")).load()
            log(f"   1-year load: {time.time()-t0:.2f}s ({one.sizes.get('time')} steps)")
            t0 = time.time()
            five = pt.sel(time=slice("2016-01-01", "2020-12-31")).load()
            log(f"   5-year load: {time.time()-t0:.2f}s ({five.sizes.get('time')} steps)")
        except Exception as e:  # noqa: BLE001
            log(f"{v}: FAIL {type(e).__name__}: {str(e)[:140]}")
    log("\nPROBE v9 COMPLETE")


if __name__ == "__main__":
    main()
