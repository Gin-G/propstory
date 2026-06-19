"""GDEX access probe v2 — drill into the real Zarr stores and open them.

Findings from v1 (run in CI):
  * OSDF/PelicanFS listing works against GDEX.
  * ERA5  d633000 exposes zarr dirs: e5.oper.an.sfc.zarr (surface analysis), etc.
  * CONUS404 d559000 is per-water-year (wy1980..wy2021) + a kerchunk/ dir.
  * xr.open_dataset("osdf://...", engine="zarr") -> ValueError: list.remove(x).

v2 deep-lists the candidate stores and tries to OPEN them via PelicanMap, then
extracts the property point to prove end-to-end access. GDEX-only.
"""

from __future__ import annotations

import traceback

LAT, LON = 40.06, -106.39
NS = "/ncar/gdex"
FED = "https://osdf-data.gdex.ucar.edu"

ERA5_SFC = f"{NS}/d633000/e5.oper.an.sfc.zarr"
CONUS404 = f"{NS}/d559000"


def fs():
    from pelicanfs.core import PelicanFileSystem
    return PelicanFileSystem(FED)


def line(c="-"):
    print(c * 72)


def ls(f, path, n=40):
    try:
        items = f.ls(path, detail=False)
        print(f"  {path}  ({len(items)} entries)")
        for it in items[:n]:
            print(f"      {it}")
        if len(items) > n:
            print(f"      ... (+{len(items)-n})")
        return items
    except Exception as e:
        print(f"  {path}  LS-ERR {type(e).__name__}: {str(e)[:140]}")
        return []


def discover():
    print("DEEP LISTING"); line()
    f = fs()
    # ERA5 surface analysis zarr: is it one store (zarr.json/.zmetadata) or many?
    era5_keys = ls(f, ERA5_SFC, n=60)
    # CONUS404 structure
    ls(f, f"{CONUS404}/kerchunk", n=40)
    ls(f, f"{CONUS404}/catalogs", n=40)
    ls(f, f"{CONUS404}/wy2021", n=40)
    ls(f, f"{NS}/d633000/catalogs", n=40)
    print()
    return era5_keys


def open_strategies(path, label):
    """Try several ways to open a zarr store from OSDF; report what works."""
    import xarray as xr
    from pelicanfs.core import PelicanFileSystem, PelicanMap
    print(f"OPEN [{label}] {path}"); line()
    f = PelicanFileSystem(FED)

    def report(ds):
        dv = list(ds.data_vars)
        print(f"    OK dims={dict(ds.sizes)}")
        print(f"    vars({len(dv)}): {dv[:16]}")
        latn = next((c for c in ("latitude", "lat", "XLAT") if c in ds), None)
        lonn = next((c for c in ("longitude", "lon", "XLONG") if c in ds), None)
        print(f"    coords lat={latn} lon={lonn} | coords={list(ds.coords)[:10]}")
        return latn, lonn

    # Strategy A: PelicanMap + open_zarr (consolidated then not)
    for consolidated in (True, False):
        try:
            m = PelicanMap(path, pelfs=f)
            ds = xr.open_zarr(m, consolidated=consolidated)
            print(f"    [A consolidated={consolidated}] success")
            report(ds)
            return ds
        except Exception as e:
            print(f"    [A consolidated={consolidated}] {type(e).__name__}: {str(e)[:140]}")

    # Strategy B: get_mapper
    try:
        m = f.get_mapper(path)
        ds = xr.open_zarr(m, consolidated=False)
        print("    [B get_mapper] success"); report(ds); return ds
    except Exception as e:
        print(f"    [B get_mapper] {type(e).__name__}: {str(e)[:140]}")

    print()
    return None


def extract(ds):
    if ds is None:
        return
    print("POINT EXTRACTION"); line()
    try:
        latn = "latitude" if "latitude" in ds else ("lat" if "lat" in ds else None)
        lonn = "longitude" if "longitude" in ds else ("lon" if "lon" in ds else None)
        var = next((v for v in ("VAR_2T", "2t", "t2m", "T2", "SNOW_ACC_NC",
                                "SNOWH", "VAR_10U", "10u") if v in ds.data_vars),
                   list(ds.data_vars)[0])
        lon = LON % 360 if float(ds[lonn].max()) > 180 else LON
        pt = ds[var].sel({latn: LAT, lonn: lon}, method="nearest")
        print(f"    var={var} cell=({float(pt[latn]):.3f},{float(pt[lonn]):.3f}) "
              f"time={ds.sizes.get('time')}")
        sample = pt.isel(time=slice(0, 3)).values if "time" in pt.dims else pt.values
        print(f"    sample values: {sample}")
    except Exception as e:
        print(f"    extract ERR {type(e).__name__}: {str(e)[:160]}")
    print()


def main():
    print("=" * 72); print("GDEX PROBE v2"); print("=" * 72)
    try:
        era5_keys = discover()
    except Exception:
        traceback.print_exc(); era5_keys = []

    # If ERA5 sfc is a single store it will contain zarr.json/.zmetadata/.zgroup.
    markers = {"zarr.json", ".zmetadata", ".zgroup"}
    era5_is_store = any(k.rstrip("/").split("/")[-1] in markers for k in era5_keys)
    print(f"ERA5 sfc looks like a single zarr store: {era5_is_store}\n")

    ds = open_strategies(ERA5_SFC, "ERA5 surface analysis")
    extract(ds)

    print("PROBE v2 COMPLETE")


if __name__ == "__main__":
    main()
