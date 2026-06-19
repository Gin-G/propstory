"""Turn a street address into a coordinate (and, optionally, an elevation).

Geocoding uses OpenStreetMap Nominatim and elevation uses Open-Elevation; both
are free and keyless. If you already have coordinates, skip this module and pass
them straight to the analysis.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
DEFAULT_USER_AGENT = "propstory/0.1 (+https://github.com/gin-g/propstory)"


@dataclass
class Location:
    """A resolved point on the Earth."""

    label: str
    lat: float
    lon: float
    display_name: str | None = None
    elevation_m: float | None = None

    @property
    def elevation_ft(self) -> float | None:
        return None if self.elevation_m is None else self.elevation_m * 3.28084


def geocode(
    address: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 20.0,
) -> Location:
    """Resolve a free-form address to a :class:`Location`.

    Raises ``LookupError`` if nothing matches.
    """
    params = urllib.parse.urlencode({"q": address, "format": "jsonv2", "limit": 1})
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}", headers={"User-Agent": user_agent}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        results = json.load(resp)
    if not results:
        raise LookupError(f"No geocoding result for {address!r}")
    top = results[0]
    return Location(
        label=address,
        lat=float(top["lat"]),
        lon=float(top["lon"]),
        display_name=top.get("display_name"),
    )


def add_elevation(
    loc: Location, *, user_agent: str = DEFAULT_USER_AGENT, timeout: float = 20.0
) -> Location:
    """Populate ``loc.elevation_m`` in place (best effort) and return it."""
    params = urllib.parse.urlencode({"locations": f"{loc.lat},{loc.lon}"})
    req = urllib.request.Request(
        f"{OPEN_ELEVATION_URL}?{params}", headers={"User-Agent": user_agent}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        loc.elevation_m = float(data["results"][0]["elevation"])
    except Exception:  # elevation is a nice-to-have, never fatal
        pass
    return loc
