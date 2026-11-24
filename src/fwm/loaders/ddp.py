"""Reading the Federal Reserve's Data Download Program packages (H.15, H.4.1, ...).

Each package is a zip holding one large SDMX XML file with every series of a
release. The program is being retired: the Fed's notice in the files says the
preformatted packages end on 2027-03-31, so these sources will need replacing.
"""

from __future__ import annotations

import datetime as dt
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from pathlib import Path

URL = "https://www.federalreserve.gov/datadownload/Output.aspx?rel={release}&filetype=zip"


def download(release: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(URL.format(release=release), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        target.write_bytes(response.read())


def parse(zip_path: Path, wanted: Callable[[str], bool]) -> tuple[dict[str, dict], dt.datetime | None]:
    """Series whose name satisfies `wanted`, and the time the file was prepared.

    Returns {series name: {"description": str, "observations": [(date, value), ...]}}.
    Only observations with status "A" (a normal value) are kept; holidays and gaps carry other codes.
    """
    out: dict[str, dict] = {}
    prepared = None
    current = None
    with zipfile.ZipFile(zip_path) as archive:
        name = next(n for n in archive.namelist() if n.endswith("_data.xml"))
        with archive.open(name) as source:
            for event, element in ET.iterparse(source, events=("start", "end")):
                tag = element.tag.rsplit("}", 1)[-1]
                if event == "start" and tag == "Series":
                    series = element.attrib.get("SERIES_NAME", "")
                    current = None
                    if wanted(series):
                        current = out[series] = {"description": None, "observations": [],
                                                 "multiplier": float(element.attrib.get("UNIT_MULT", 1))}
                elif event == "end" and tag == "AnnotationText":
                    if current is not None and current["description"] is None:
                        current["description"] = (element.text or "").strip()
                elif event == "end" and tag == "Obs":
                    if current is not None and element.attrib.get("OBS_STATUS") == "A":
                        current["observations"].append((
                            dt.date.fromisoformat(element.attrib["TIME_PERIOD"]),
                            float(element.attrib["OBS_VALUE"]),
                        ))
                    element.clear()
                elif event == "end" and tag == "Series":
                    element.clear()
                elif event == "end" and tag == "Prepared" and element.text:
                    prepared = dt.datetime.fromisoformat(element.text.strip())
    return out, prepared
