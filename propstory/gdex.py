"""Reusable GDEX access (the recipe reverse-engineered via CI trial-and-error).

GDEX is the only data source. Two datasets:

  ERA5  d633000 : per-variable surface zarr stores, opened with PelicanMap +
                  consolidated metadata. Hourly, 1940-present, 0.25 deg, global.
                    e5.oper.an.sfc.zarr/e5.oper.an.sfc.<var>.zarr
                  var codes: sd (snow depth, m w.e.), 2t, 10u, 10v, rsn, ...
  CONUS404 d559000 : 4 km hourly WRF. Raw = hourly NetCDF; multi-time access via
                  kerchunk virtual-zarr refs (kerchunk/wy<YYYY>.2d-https.json).

OSDF reads occasionally raise transient payload errors, so reads are retried.
"""

from __future__ import annotations

import io
import time

HTTPS = "https://osdf-data.gdex.ucar.edu"
NS = "/ncar/gdex"
ERA5_SFC = f"{NS}/d633000/e5.oper.an.sfc.zarr"

# logical name -> (ERA5 surface var code, human description, units after convert)
ERA5_SURFACE = {
    "snow_depth_we": ("sd", "snow depth (water equivalent)"),
    "snow_density": ("rsn", "snow density"),
    "t2": ("2t", "2 m temperature"),
    "u10": ("10u", "10 m u-wind"),
    "v10": ("10v", "10 m v-wind"),
}


def _log(msg):
    print(msg, flush=True)


def retry(fn, attempts=5, base=2.0, label=""):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            _log(f"    retry {i+1}/{attempts} {label} after {type(e).__name__}: {str(e)[:90]}")
            time.sleep(base * (i + 1))
    raise last


def _pelfs():
    from pelicanfs.core import PelicanFileSystem
    return PelicanFileSystem(HTTPS)


# --------------------------------------------------------------------------- ERA5
def open_era5_var(code: str):
    """Open one ERA5 surface variable store as an xarray Dataset (lazy)."""
    import xarray as xr
    from pelicanfs.core import PelicanMap
    f = _pelfs()
    store = f"{ERA5_SFC}/e5.oper.an.sfc.{code}.zarr"
    return retry(lambda: xr.open_dataset(PelicanMap(store, pelfs=f),
                                         engine="zarr", consolidated=True),
                 label=f"open era5 {code}")


def era5_point(lat: float, lon: float, logical_vars=None, time_slice=None):
    """Return an xarray Dataset of ERA5 surface vars at the nearest grid point.

    Variables are renamed to their logical names (snow_depth_we, t2, ...).
    """
    import xarray as xr
    logical_vars = logical_vars or list(ERA5_SURFACE)
    pieces = {}
    for logical in logical_vars:
        code, _desc = ERA5_SURFACE[logical]
        ds = open_era5_var(code)
        var = list(ds.data_vars)[0]
        lon_sel = lon % 360 if float(ds["longitude"].max()) > 180 else lon
        da = ds[var].sel(latitude=lat, longitude=lon_sel, method="nearest")
        if time_slice is not None:
            da = da.sel(time=slice(*time_slice))
        da.attrs["gdex_units"] = ds[var].attrs.get("units", "")
        pieces[logical] = da
    out = xr.Dataset(pieces)
    out.attrs["gdex_dataset"] = "d633000 (ERA5)"
    out.attrs["grid_lat"] = float(out[logical_vars[0]].latitude)
    out.attrs["grid_lon"] = float(out[logical_vars[0]].longitude)
    return out


# ----------------------------------------------------------------------- CONUS404
def conus404_kerchunk_url(water_year: int, kind: str = "2d") -> str:
    return f"{HTTPS}{NS}/d559000/kerchunk/wy{water_year}.{kind}-https.json"


def open_conus404_year(water_year: int, kind: str = "2d"):
    """Open a CONUS404 water year as a virtual zarr via its kerchunk reference."""
    import fsspec
    import xarray as xr
    url = conus404_kerchunk_url(water_year, kind)

    def _open():
        fs = fsspec.filesystem("reference", fo=url, remote_protocol="https")
        return xr.open_dataset(fs.get_mapper(""), engine="zarr",
                               consolidated=False, chunks={})
    return retry(_open, label=f"open conus404 wy{water_year}")


def open_conus404_nc(path_https: str):
    """Open a single CONUS404 hourly NetCDF file from its HTTPS URL."""
    import fsspec
    import xarray as xr
    data = retry(lambda: fsspec.open(path_https, "rb").open().read(),
                 label="fetch conus404 nc")
    return xr.open_dataset(io.BytesIO(data), engine="h5netcdf")


def nearest_curvilinear(lat2d, lon2d, lat, lon):
    """Index of nearest cell on a curvilinear (XLAT/XLONG) grid."""
    import numpy as np
    la = np.asarray(lat2d).squeeze()
    lo = np.asarray(lon2d).squeeze()
    lo = np.where(lo > 180, lo - 360, lo)
    d = (la - lat) ** 2 + (lo - lon) ** 2
    iy, ix = np.unravel_index(int(np.argmin(d)), d.shape)
    return int(iy), int(ix), float(la[iy, ix]), float(lo[iy, ix])
