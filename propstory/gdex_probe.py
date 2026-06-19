"""GDEX access probe v4 — open real Zarr stores (metadata-only), extract a point.

v3 was canceled mid-run: downloading a full-water-year CONUS404 kerchunk JSON
(hundreds of MB) via requests.json() was too heavy. v4 instead opens an actual
Zarr *store* (reads only metadata + the chunks for one point) via PelicanMap, and
discovers the real store paths adaptively. Everything flushes so the CI log shows
progress even if a step stalls. GDEX-only.
"""

from __future__ import annotations

import sys
import traceback

LAT, LON = 40.06, -106.39
HTTPS = "https://osdf-data.gdex.ucar.edu"
NS = "/ncar/gdex"


def log(*a):
    print(*a, flush=True)


def line():
    log("-" * 72)


def fs():
    from pelicanfs.core import PelicanFileSystem
    return PelicanFileSystem(HTTPS)


def ls(f, path, n=30):
    try:
        items = f.ls(path, detail=False)
        log(f"  {path} ({len(items)})")
        for it in items[:n]:
            log(f"      {it}")
        if len(items) > n:
            log(f"      ... (+{len(items)-n})")
        return items
    except Exception as e:
        log(f"  {path} LS-ERR {type(e).__name__}: {str(e)[:120]}")
        return []


def looks_like_store(f, path):
    """True if path contains zarr metadata markers."""
    try:
        kids = {k.rstrip('/').split('/')[-1] for k in f.ls(path, detail=False)}
        return bool(kids & {"zarr.json", ".zgroup", ".zmetadata", ".zattrs"})
    except Exception:
        return False


def try_open(path, label):
    import xarray as xr
    from pelicanfs.core import PelicanFileSystem, PelicanMap
    log(f"OPEN [{label}] {path}"); line()
    f = PelicanFileSystem(HTTPS)
    for consolidated in (True, False):
        try:
            ds = xr.open_dataset(PelicanMap(path, pelfs=f), engine="zarr",
                                 consolidated=consolidated, chunks={})
            dv = list(ds.data_vars)
            log(f"    [cons={consolidated}] OK dims={dict(ds.sizes)}")
            log(f"    vars({len(dv)}): {dv[:24]}")
            log(f"    coords: {list(ds.coords)[:12]}")
            return ds
        except Exception as e:
            log(f"    [cons={consolidated}] {type(e).__name__}: {str(e)[:130]}")
    return None


def extract(ds, label):
    if ds is None:
        return
    import numpy as np
    log(f"POINT EXTRACT [{label}]"); line()
    try:
        latn = next((c for c in ("latitude", "lat", "XLAT", "XLAT_M") if c in ds), None)
        lonn = next((c for c in ("longitude", "lon", "XLONG", "XLONG_M") if c in ds), None)
        lat = ds[latn].values
        lon = ds[lonn].values
        var = list(ds.data_vars)[0]
        for cand in ("SNOW", "SNOWH", "T2", "PREC_ACC_NC", "ACSNOW", "U10", "V10",
                     "VAR_2T", "SD", "SF", "VAR_10U"):
            if cand in ds.data_vars:
                var = cand; break
        if getattr(lat, "ndim", 1) >= 2:           # curvilinear
            la = lat[0] if lat.ndim == 3 else lat
            lo = lon[0] if lon.ndim == 3 else lon
            lo180 = np.where(lo > 180, lo - 360, lo)
            d = (la - LAT) ** 2 + (lo180 - LON) ** 2
            iy, ix = np.unravel_index(int(np.argmin(d)), d.shape)
            ydim, xdim = ds[var].dims[-2], ds[var].dims[-1]
            pt = ds[var].isel({ydim: iy, xdim: ix})
            log(f"    cell=({float(la[iy,ix]):.3f},{float(lo180[iy,ix]):.3f}) var={var}")
        else:                                       # rectilinear
            lonsel = LON % 360 if float(np.max(lon)) > 180 else LON
            pt = ds[var].sel({latn: LAT, lonn: lonsel}, method="nearest")
            log(f"    cell=({float(pt[latn]):.3f},{float(pt[lonn]):.3f}) var={var}")
        tdim = next((d for d in ("time", "Time", "valid_time") if d in pt.dims), None)
        vals = pt.isel({tdim: slice(0, 3)}).values if tdim else pt.values
        log(f"    sample {var}: {np.asarray(vals).ravel()[:3]}")
    except Exception as e:
        log(f"    extract ERR {type(e).__name__}: {str(e)[:160]}")
        traceback.print_exc()
    log("")


def discover_conus404(f):
    log("CONUS404 DISCOVERY"); line()
    month = ls(f, f"{NS}/d559000/wy2021/202101", n=30)
    store = None
    for it in month:
        if it.rstrip('/').endswith('.zarr') or looks_like_store(f, it):
            store = it; break
    log(f"  -> candidate store: {store}\n")
    return store


def discover_era5(f):
    log("ERA5 DISCOVERY"); line()
    top = ls(f, f"{NS}/d633000/e5.oper.an.sfc.zarr", n=30)
    store = None
    for it in top:
        if it.rstrip('/').endswith('.zarr') or looks_like_store(f, it):
            store = it; break
    if store is None and top:
        # one level deeper
        child = ls(f, top[0], n=30)
        for it in child:
            if it.rstrip('/').endswith('.zarr') or looks_like_store(f, it):
                store = it; break
    log(f"  -> candidate store: {store}\n")
    return store


def main():
    log("=" * 72); log("GDEX PROBE v4 (open real stores)"); log("=" * 72)
    f = fs()
    try:
        c = discover_conus404(f)
        extract(try_open(c, "CONUS404 monthly"), "CONUS404") if c else log("no CONUS404 store\n")
    except Exception:
        traceback.print_exc()
    try:
        e = discover_era5(f)
        extract(try_open(e, "ERA5 sfc var"), "ERA5") if e else log("no ERA5 store\n")
    except Exception:
        traceback.print_exc()
    log("PROBE v4 COMPLETE")


if __name__ == "__main__":
    sys.exit(main())
