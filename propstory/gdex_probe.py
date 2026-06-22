"""GDEX probe v7 — can a BROWSER query GDEX directly? (CORS) + find Sentinel-2.

For an in-browser front end, cross-origin fetch() of GDEX data requires the
server to send Access-Control-Allow-Origin. This checks that on the OSDF origin
(zarr metadata, a data chunk, and a kerchunk json), following redirects, and
prints the CORS headers on the FINAL response. It also searches GDEX for any
Sentinel-2 holdings.
"""

from __future__ import annotations

import re
import requests

ORIGIN = "https://gin-g.github.io"
SAMPLE = {
    "ERA5 sd .zmetadata":
        "https://osdf-data.gdex.ucar.edu/ncar/gdex/d633000/e5.oper.an.sfc.zarr/"
        "e5.oper.an.sfc.sd.zarr/.zmetadata",
    "ERA5 sd zarr.json":
        "https://osdf-data.gdex.ucar.edu/ncar/gdex/d633000/e5.oper.an.sfc.zarr/"
        "e5.oper.an.sfc.sd.zarr/zarr.json",
    "CONUS404 kerchunk wy2021.2d-https.json":
        "https://osdf-data.gdex.ucar.edu/ncar/gdex/d559000/kerchunk/wy2021.2d-https.json",
}


def cors_headers(h):
    return {k: v for k, v in h.items() if k.lower().startswith("access-control")}


def check(url):
    print(f"\nURL: {url}")
    # simple GET with Origin
    try:
        r = requests.get(url, headers={"Origin": ORIGIN}, timeout=60,
                         stream=True, allow_redirects=True)
        chain = " -> ".join(str(h.status_code) for h in r.history) or "(no redirect)"
        print(f"  GET  status={r.status_code} redirects={chain}")
        print(f"       final_url={r.url[:110]}")
        cors = cors_headers(r.headers)
        print(f"       CORS={cors if cors else 'NONE'}")
        r.close()
    except Exception as e:
        print(f"  GET  ERR {type(e).__name__}: {str(e)[:120]}")
    # preflight
    try:
        r = requests.options(url, headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "range",
        }, timeout=60, allow_redirects=True)
        print(f"  OPT  status={r.status_code} CORS={cors_headers(r.headers) or 'NONE'}")
    except Exception as e:
        print(f"  OPT  ERR {type(e).__name__}: {str(e)[:120]}")


def find_sentinel2():
    print("\n" + "=" * 60)
    print("SENTINEL-2 ON GDEX?")
    for url in ("https://gdex.ucar.edu/datasets/?q=sentinel",
                "https://gdex.ucar.edu/search/?q=sentinel-2",
                "https://gdex.ucar.edu/datasets/?search=sentinel"):
        try:
            r = requests.get(url, timeout=40)
            ids = sorted(set(re.findall(r"d\d{6}", r.text)))
            sent = "sentinel" in r.text.lower()
            print(f"  {url} -> {r.status_code}, mentions 'sentinel'={sent}, dataset ids={ids[:12]}")
        except Exception as e:
            print(f"  {url} ERR {type(e).__name__}: {str(e)[:100]}")


def main():
    print("=" * 60)
    print("GDEX PROBE v7 — CORS + Sentinel-2")
    print("=" * 60)
    for label, url in SAMPLE.items():
        print(f"\n### {label}")
        check(url)
    find_sentinel2()
    print("\nPROBE v7 COMPLETE")


if __name__ == "__main__":
    main()
