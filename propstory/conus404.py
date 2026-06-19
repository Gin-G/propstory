"""Access CONUS404 from NSF NCAR GDEX and select the cell over a point.

CONUS404 is the NCAR/USGS 4 km, hourly, ~40-year (water years 1980-2022)
regional hydroclimate reanalysis produced by dynamically downscaling ERA5 with
WRF. GDEX serves it as analysis-ready Zarr, streamable over the Open Science
Data Federation (OSDF) with PelicanFS -- no NCAR HPC account required.

  GDEX dataset id : d559000   (formerly RDA ds559.0)
  OSDF namespace  : osdf:///ncar/gdex/d559000/...

The grid is curvilinear (Lambert Conformal), so a point is selected by nearest
neighbour on the 2-D latitude/longitude fields rather than a label-based
``.sel``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GDEX_DATASET_ID = "d559000"
OSDF_BASE = f"osdf:///ncar/gdex/{GDEX_DATASET_ID}"

#: Default GDEX/OSDF zarr store. The exact leaf name should be confirmed against
#: the live GDEX catalog (https://gdex.ucar.edu/datasets/d559000/); it is exposed
#: as a CLI argument precisely so it can be overridden without code changes.
DEFAULT_OSDF_STORE = f"{OSDF_BASE}/conus404_hourly.zarr"

#: HyTEST publishes the same CONUS404 data with stable, documented zarr paths.
HYTEST_CATALOG = (
    "https://raw.githubusercontent.com/hytest-org/hytest/main/"
    "dataset_catalog/hytest_intake_catalog.yml"
)
DEFAULT_HYTEST_SOURCE = "conus404-hourly-osn"

#: Logical name -> candidate variable names in the store (first match wins).
VARIABLE_ALIASES = {
    "swe": ("SNOW", "snow", "swe"),               # snow water equivalent, kg m-2 == mm
    "snow_depth": ("SNOWH", "snowh", "snow_depth"),  # physical snow depth, m
    "precip": ("PREC_ACC_NC", "prec_acc_nc", "precip"),  # precip per output step, mm
    "snowfall": ("ACSNOW", "acsnow"),             # accumulated snowfall bucket, mm
    "t2": ("T2", "t2", "T2D"),                    # 2 m air temperature, K
    "u10": ("U10", "u10"),                        # 10 m u-wind, m s-1
    "v10": ("V10", "v10"),                        # 10 m v-wind, m s-1
}


@dataclass
class CellSelection:
    """The CONUS404 grid cell chosen for a point."""

    iy: int
    ix: int
    grid_lat: float
    grid_lon: float
    distance_km: float
    ydim: str
    xdim: str


def open_conus404(store: str | None = None, *, backend: str = "osdf", chunks="auto"):
    """Open CONUS404 lazily as an :class:`xarray.Dataset`.

    ``backend='osdf'`` streams from GDEX via PelicanFS; ``backend='hytest'`` uses
    the published HyTEST intake catalog as a verified fallback.
    """
    import xarray as xr

    if backend == "osdf":
        import pelicanfs  # noqa: F401  (registers the 'osdf://' fsspec protocol)

        store = store or DEFAULT_OSDF_STORE
        return xr.open_dataset(store, engine="zarr", chunks=chunks)

    if backend == "hytest":
        import intake

        cat = intake.open_catalog(HYTEST_CATALOG)
        return cat[store or DEFAULT_HYTEST_SOURCE].to_dask()

    raise ValueError(f"unknown backend {backend!r} (use 'osdf' or 'hytest')")


def _grid_latlon(ds):
    """Return (lat2d, lon2d, ydim, xdim) for a CONUS404-style dataset."""
    lat_name = next((n for n in ("lat", "XLAT", "latitude", "south_north") if n in ds), None)
    lon_name = next((n for n in ("lon", "XLONG", "longitude", "west_east") if n in ds), None)
    if lat_name is None or lon_name is None:
        raise KeyError("could not locate latitude/longitude coordinates in dataset")

    lat = ds[lat_name]
    lon = ds[lon_name]
    # Native WRF dims are south_north / west_east; HyTEST renames to y / x.
    ydim = next((d for d in ("y", "south_north") if d in ds.dims), lat.dims[0])
    xdim = next((d for d in ("x", "west_east") if d in ds.dims), lat.dims[-1])

    lat2d = np.asarray(lat.values)
    lon2d = np.asarray(lon.values)
    if lat2d.ndim == 1 and lon2d.ndim == 1:  # rectilinear fallback
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lat2d, lon2d, ydim, xdim


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p = np.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin(dlon / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def nearest_cell(ds, lat: float, lon: float) -> CellSelection:
    """Find the grid cell whose centre is closest to ``(lat, lon)``."""
    lat2d, lon2d, ydim, xdim = _grid_latlon(ds)
    dist = _haversine_km(lat, lon, lat2d, lon2d)
    iy, ix = np.unravel_index(int(np.argmin(dist)), dist.shape)
    return CellSelection(
        iy=int(iy),
        ix=int(ix),
        grid_lat=float(lat2d[iy, ix]),
        grid_lon=float(lon2d[iy, ix]),
        distance_km=float(dist[iy, ix]),
        ydim=ydim,
        xdim=xdim,
    )


def point_timeseries(ds, sel: CellSelection):
    """Slice the dataset down to the single selected cell (a time series)."""
    return ds.isel({sel.ydim: sel.iy, sel.xdim: sel.ix})


def resolve_variables(ds) -> dict[str, str]:
    """Map logical names to the actual variable names present in ``ds``."""
    found = {}
    for logical, candidates in VARIABLE_ALIASES.items():
        match = next((c for c in candidates if c in ds.variables), None)
        if match is not None:
            found[logical] = match
    return found
