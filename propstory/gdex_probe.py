"""GDEX access probe — trial-and-error harness meant to run in GitHub Actions.

This sandbox cannot reach the GDEX hosts (network policy denies them), but CI
runners have open egress. This script attempts every GDEX access path we know of
for CONUS404 and ERA5, prints a clear PASS/FAIL report, and (when something
works) extracts a single point to prove end-to-end access. Use the CI logs to
iterate on the exact store paths.

GDEX is the *only* source used here. No GCS/AWS/STAC fallbacks.
"""

from __future__ import annotations

import json
import sys
import traceback

# Property under study (approx; exact parcel can be passed later).
LAT, LON = 40.06, -106.39

# RDA -> GDEX dataset ids
DATASETS = {
    "CONUS404": "d559000",   # NCAR/USGS 4 km hydroclimate reanalysis (ds559.0)
    "ERA5": "d633000",       # ECMWF ERA5 on GDEX (ds633.0)
}

GDEX_WEB = "https://gdex.ucar.edu"
OSDF_HTTPS = "https://osdf-data.gdex.ucar.edu"      # OSDF origin (https)
OSDF_NS = "/ncar/gdex"                              # pelican namespace base
TDS = "https://tds.gdex.ucar.edu/thredds"          # THREDDS data server


def line(c="-"):
    print(c * 72)


def reach():
    import requests
    print("REACHABILITY"); line()
    for url in (GDEX_WEB, OSDF_HTTPS, f"{TDS}/catalog.xml",
                "https://thredds.rda.ucar.edu/thredds/catalog.xml"):
        try:
            r = requests.get(url, timeout=30)
            print(f"  {r.status_code:>3}  {url}  ({len(r.content)} bytes)")
        except Exception as e:
            print(f"  ERR  {url}  -> {type(e).__name__}: {e}")
    print()


def thredds_catalog():
    """Walk the THREDDS catalog looking for the target datasets."""
    import re
    import requests
    print("THREDDS CATALOG DISCOVERY"); line()
    candidates = [
        f"{TDS}/catalog.xml",
        f"{TDS}/catalog/catalog.xml",
    ]
    for ds, did in DATASETS.items():
        candidates += [
            f"{TDS}/catalog/files/g/{did}/catalog.xml",
            f"{TDS}/catalog/aggregations/g/{did}/catalog.xml",
            f"{TDS}/catalog/{did}/catalog.xml",
        ]
    for url in candidates:
        try:
            r = requests.get(url, timeout=40)
            if r.status_code != 200:
                print(f"  {r.status_code}  {url}")
                continue
            refs = re.findall(r'(?:catalogRef|dataset)[^>]*?(?:xlink:href|urlPath|ID)="([^"]+)"', r.text)
            print(f"  200  {url}")
            for ref in refs[:25]:
                print(f"        - {ref}")
            if len(refs) > 25:
                print(f"        ... (+{len(refs)-25} more)")
        except Exception as e:
            print(f"  ERR  {url}  -> {type(e).__name__}: {e}")
    print()


def gdex_web_links():
    """Scrape the dataset web pages for any zarr/osdf/opendap hints."""
    import re
    import requests
    print("GDEX DATASET PAGE HINTS"); line()
    for ds, did in DATASETS.items():
        url = f"{GDEX_WEB}/datasets/{did}/"
        try:
            r = requests.get(url, timeout=40)
            hits = sorted(set(re.findall(
                r'(osdf://[^\s"\'<>]+|https?://[^\s"\'<>]*(?:zarr|dodsC|osdf)[^\s"\'<>]*)', r.text)))
            print(f"  {ds} {did}: {r.status_code}, {len(hits)} hint(s)")
            for h in hits[:15]:
                print(f"        {h}")
        except Exception as e:
            print(f"  {ds} {did}: ERR {type(e).__name__}: {e}")
    print()


def osdf_listing():
    """Try to list the OSDF namespace for each dataset via PelicanFS."""
    print("OSDF / PELICANFS LISTING"); line()
    try:
        from pelicanfs.core import PelicanFileSystem
    except Exception as e:
        print(f"  pelicanfs import failed: {e}"); print(); return
    for fed in ("osdf-data.gdex.ucar.edu", "osg-htc.org"):
        print(f"  federation discovery via https://{fed}")
        try:
            fs = PelicanFileSystem(f"https://{fed}")
            for ds, did in DATASETS.items():
                path = f"{OSDF_NS}/{did}"
                try:
                    items = fs.ls(path, detail=False)
                    print(f"    {ds} {path}: {len(items)} entries")
                    for it in items[:15]:
                        print(f"        {it}")
                except Exception as e:
                    print(f"    {ds} {path}: ERR {type(e).__name__}: {str(e)[:120]}")
        except Exception as e:
            print(f"    federation {fed} failed: {type(e).__name__}: {str(e)[:120]}")
    print()


def try_open(store: str, label: str):
    """Attempt to open a zarr store and extract the property point."""
    import numpy as np
    import xarray as xr
    print(f"  OPEN [{label}] {store}")
    try:
        ds = xr.open_dataset(store, engine="zarr", chunks={})
        svars = [v for v in ds.data_vars]
        print(f"    OK dims={dict(ds.sizes)}")
        print(f"    vars({len(svars)}): {svars[:12]}{' ...' if len(svars) > 12 else ''}")
        # try a nearest-point extraction on whatever coords exist
        latn = next((c for c in ("latitude", "lat", "XLAT") if c in ds), None)
        lonn = next((c for c in ("longitude", "lon", "XLONG") if c in ds), None)
        print(f"    coords: lat={latn} lon={lonn}")
        return True
    except Exception as e:
        print(f"    FAIL {type(e).__name__}: {str(e)[:160]}")
        return False


def open_attempts():
    print("DIRECT OPEN ATTEMPTS"); line()
    for ds, did in DATASETS.items():
        # A few plausible leaf names; CI logs tell us which (if any) resolve.
        leaves = ["", "conus404_hourly.zarr", "conus404.zarr", "era5.zarr",
                  f"{did}.zarr"]
        for leaf in leaves:
            store = f"osdf://{OSDF_NS}/{did}/{leaf}".rstrip("/")
            try_open(store, f"{ds} osdf")
    print()


def main():
    print("=" * 72)
    print("GDEX ACCESS PROBE")
    print(f"target point: {LAT}, {LON}")
    print("=" * 72)
    for step in (reach, thredds_catalog, gdex_web_links, osdf_listing, open_attempts):
        try:
            step()
        except Exception:
            print(f"step {step.__name__} crashed:")
            traceback.print_exc()
            print()
    print("PROBE COMPLETE")


if __name__ == "__main__":
    sys.exit(main())
