"""Command-line entry point: ``python -m propstory ...``"""

from __future__ import annotations

import argparse
import sys

from . import conus404, geocode
from .climatology import compute
from .conus404 import GDEX_DATASET_ID, OSDF_BASE, DEFAULT_OSDF_STORE
from .report import render


def _resolve_location(args) -> geocode.Location:
    if args.lat is not None and args.lon is not None:
        loc = geocode.Location(label=args.label or f"{args.lat},{args.lon}",
                               lat=args.lat, lon=args.lon)
    elif args.address:
        loc = geocode.geocode(args.address)
        if args.label:
            loc.label = args.label
        geocode.add_elevation(loc)
    else:
        raise SystemExit("provide --address, or both --lat and --lon")
    return loc


def _dry_run(args) -> int:
    """Explain exactly what would be fetched, touching no network."""
    store = args.store or (DEFAULT_OSDF_STORE if args.backend == "osdf" else "<hytest catalog source>")
    target = args.address or f"({args.lat}, {args.lon})"
    print("PropStory dry run")
    print("=================")
    print(f"  target           : {target}")
    print( "  1. geocode       : OpenStreetMap Nominatim -> lat/lon (+ elevation)")
    print(f"  2. open dataset  : backend={args.backend!r}")
    print(f"       GDEX id     : {GDEX_DATASET_ID} (CONUS404, 4 km hourly reanalysis)")
    print(f"       OSDF base   : {OSDF_BASE}")
    print(f"       store       : {store}")
    print( "       reader      : xarray.open_dataset(..., engine='zarr') over PelicanFS")
    print( "  3. select cell   : nearest neighbour on 2-D lat/lon (Lambert Conformal grid)")
    print( "  4. variables     : SNOW(SWE), SNOWH(depth), PREC_ACC_NC, ACSNOW, T2, U10, V10")
    print( "  5. climatology   : water-year snowfall, peak SWE, skiable days, wind, trends")
    print(f"  6. report        : markdown -> {args.out or 'stdout'}")
    print()
    print("No network was contacted. Re-run without --dry-run (with pelicanfs installed")
    print("and the GDEX/OSDF host reachable) to produce the data-driven report.")
    return 0


def cmd_analyze(args) -> int:
    if args.dry_run:
        return _dry_run(args)

    loc = _resolve_location(args)
    print(f"[propstory] location: {loc.lat:.5f}, {loc.lon:.5f}", file=sys.stderr)

    ds = conus404.open_conus404(store=args.store, backend=args.backend)
    sel = conus404.nearest_cell(ds, loc.lat, loc.lon)
    print(f"[propstory] grid cell {sel.distance_km:.1f} km away", file=sys.stderr)

    variables = conus404.resolve_variables(ds)
    if not variables:
        raise SystemExit("no known CONUS404 variables found in the opened store")

    pt = conus404.point_timeseries(ds, sel).load()
    clim = compute(pt, variables)
    md = render(loc, sel, clim, title=args.label)
    _emit(md, args.out)
    return 0


def cmd_demo(args) -> int:
    """Run the whole pipeline against a synthetic CONUS404-like cube (offline)."""
    from .demo import synthetic_dataset

    loc = geocode.Location(label="Demo Ridge (synthetic)", lat=40.06, lon=-106.39,
                           elevation_m=2300.0)
    ds = synthetic_dataset(center=(loc.lat, loc.lon))
    sel = conus404.nearest_cell(ds, loc.lat, loc.lon)
    variables = conus404.resolve_variables(ds)
    pt = conus404.point_timeseries(ds, sel)
    clim = compute(pt, variables)
    md = render(loc, sel, clim, title=loc.label, synthetic=True)
    _emit(md, args.out)
    return 0


def _emit(md: str, out: str | None) -> None:
    if out:
        import pathlib
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(out).write_text(md)
        print(f"[propstory] wrote {out}", file=sys.stderr)
    else:
        print(md)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="propstory", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="build a propstory for an address or point")
    a.add_argument("--address")
    a.add_argument("--lat", type=float)
    a.add_argument("--lon", type=float)
    a.add_argument("--label", help="title / display label for the report")
    a.add_argument("--backend", choices=["osdf", "hytest"], default="osdf")
    a.add_argument("--store", help="override zarr store / catalog source")
    a.add_argument("--out", help="output markdown path (default: stdout)")
    a.add_argument("--dry-run", action="store_true",
                   help="print the plan without touching the network")
    a.set_defaults(func=cmd_analyze)

    d = sub.add_parser("demo", help="run the pipeline on synthetic data (offline)")
    d.add_argument("--out", help="output markdown path (default: stdout)")
    d.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
