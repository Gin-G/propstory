"""GDEX access probe v3 — open via kerchunk virtual-zarr references (HTTPS).

v2 findings:
  * CONUS404 d559000 has kerchunk refs: kerchunk/wy<YYYY>.{2d,3d}-{https,osdf}.json
    - 2d = surface fields (snow, wind, temp, precip)  <-- what we need
    - the -https variant points chunk reads at plain HTTPS, avoiding the
      pelicanfs+zarr 'list.remove' bug.
  * ERA5 d633000/e5.oper.an.sfc.zarr is a directory of sub-stores, not one group.

v3 opens the CONUS404 2d kerchunk reference over HTTPS and extracts the property
point, and inspects ERA5's substore layout + kerchunk. GDEX-only.
"""

from __future__ import annotations

import json
import traceback

import requests

LAT, LON = 40.06, -106.39
HTTPS = "https://osdf-data.gdex.ucar.edu"          # OSDF origin also serves plain HTTPS
NS = "/ncar/gdex"


def line(c="-"):
    print(c * 72)


def http_json(url):
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    return r.json()


def open_kerchunk(ref_url, label):
    """Open a kerchunk reference (HTTPS remote) as an xarray dataset."""
    import fsspec
    import xarray as xr
    print(f"OPEN [{label}] {ref_url}"); line()
    try:
        refs = http_json(ref_url)
        nkeys = len(refs.get("refs", refs))
        print(f"    fetched reference ({nkeys} keys)")
    except Exception as e:
        print(f"    fetch FAIL {type(e).__name__}: {str(e)[:160]}"); return None
    for consolidated in (True, False):
        try:
            fs = fsspec.filesystem("reference", fo=refs, remote_protocol="https")
            ds = xr.open_dataset(fs.get_mapper(""), engine="zarr",
                                 consolidated=consolidated, chunks={})
            print(f"    [consolidated={consolidated}] OK dims={dict(ds.sizes)}")
            dv = list(ds.data_vars)
            print(f"    vars({len(dv)}): {dv[:24]}")
            print(f"    coords: {list(ds.coords)[:12]}")
            return ds
        except Exception as e:
            print(f"    [consolidated={consolidated}] {type(e).__name__}: {str(e)[:150]}")
    return None


def extract_conus404(ds):
    if ds is None:
        return
    print("CONUS404 POINT EXTRACTION (curvilinear nearest cell)"); line()
    import numpy as np
    try:
        latn = next(c for c in ("XLAT", "lat", "latitude") if c in ds)
        lonn = next(c for c in ("XLONG", "lon", "longitude") if c in ds)
        lat2d = np.asarray(ds[latn].values)
        lon2d = np.asarray(ds[lonn].values)
        if lat2d.ndim == 3:
            lat2d, lon2d = lat2d[0], lon2d[0]
        d = (lat2d - LAT) ** 2 + (np.where(lon2d > 180, lon2d - 360, lon2d) - LON) ** 2
        iy, ix = np.unravel_index(int(np.argmin(d)), d.shape)
        print(f"    nearest cell idx=({iy},{ix}) at "
              f"({float(lat2d[iy, ix]):.3f},{float(lon2d[iy, ix]):.3f})")
        var = next((v for v in ("SNOW", "SNOWH", "T2", "PREC_ACC_NC", "ACSNOW",
                                "U10", "V10") if v in ds.data_vars),
                   list(ds.data_vars)[0])
        ydim, xdim = ds[var].dims[-2], ds[var].dims[-1]
        pt = ds[var].isel({ydim: iy, xdim: ix})
        sample = pt.isel(Time=slice(0, 3)).values if "Time" in pt.dims else (
            pt.isel(time=slice(0, 3)).values if "time" in pt.dims else pt.values)
        print(f"    {var} sample: {sample}")
    except Exception as e:
        print(f"    extract ERR {type(e).__name__}: {str(e)[:160]}")
        traceback.print_exc()
    print()


def inspect_era5():
    print("ERA5 SUBSTORE / KERCHUNK INSPECTION"); line()
    from pelicanfs.core import PelicanFileSystem
    f = PelicanFileSystem(HTTPS)
    for p in (f"{NS}/d633000/e5.oper.an.sfc.zarr",
              f"{NS}/d633000/kerchunk"):
        try:
            items = f.ls(p, detail=False)
            print(f"  {p} ({len(items)})")
            for it in items[:20]:
                print(f"      {it}")
            if len(items) > 20:
                print(f"      ... (+{len(items)-20})")
            # one level deeper into first dir
            subs = [i for i in items if i.endswith("/")]
            if subs:
                child = f.ls(subs[0], detail=False)
                print(f"    child {subs[0]} ({len(child)}): {child[:8]}")
        except Exception as e:
            print(f"  {p} ERR {type(e).__name__}: {str(e)[:140]}")
    print()


def main():
    print("=" * 72); print("GDEX PROBE v3 (kerchunk/https)"); print("=" * 72)
    # CONUS404 surface (2d) for a recent water year
    ref = f"{HTTPS}{NS}/d559000/kerchunk/wy2021.2d-https.json"
    ds = open_kerchunk(ref, "CONUS404 wy2021 2d")
    extract_conus404(ds)
    try:
        inspect_era5()
    except Exception:
        traceback.print_exc()
    print("PROBE v3 COMPLETE")


if __name__ == "__main__":
    main()
