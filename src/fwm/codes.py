"""Country codes: the one place the Treasury's names, the BIS's two-letter codes and the IMF's three-letter codes meet.

The table is curated/country_codes.csv.
"""

from __future__ import annotations

import csv
import functools
import re
import unicodedata

from fwm.paths import CURATED

CODES_PATH = CURATED / "country_codes.csv"


@functools.lru_cache(maxsize=1)
def load_codes() -> list[dict]:
    """Every country both sources know: ISO two- and three-letter codes, a short name, and other names it goes by."""
    with CODES_PATH.open(newline="", encoding="utf-8") as source:
        return [dict(row, aliases=[a for a in row["aliases"].split(";") if a]) for row in csv.DictReader(source)]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("-")


def find_country(name: str) -> dict | None:
    """The code-table row for a country given by name, another name it goes by, or either ISO code."""
    return _by_name().get(_slug(name))


@functools.lru_cache(maxsize=1)
def _by_name() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in load_codes():
        for key in (row["iso3"].lower(), *map(_slug, row["aliases"]), _slug(row["imf_name"]), _slug(row["name"])):
            out.setdefault(key, row)
    # Two-letter codes last, so that a code never shadows a name.
    for row in load_codes():
        out.setdefault(row["iso2"].lower(), row)
    return out
