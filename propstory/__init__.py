"""PropStory: historical representation of an address from NSF NCAR GDEX
analysis-ready data (CONUS404)."""

__version__ = "0.1.0"

from . import geocode  # noqa: F401  (submodule; keep importable as propstory.geocode)
from .geocode import Location  # noqa: F401
