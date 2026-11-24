"""Where things live on disk."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
RAW = ROOT / "data" / "raw"                      # downloads, one folder per source
DB_PATH = Path(os.environ.get("FWM_DB", ROOT / "data" / "fwm.duckdb"))
CURATED = PACKAGE / "curated"                    # files maintained by hand: announcements, country codes
WEB_DIST = ROOT / "web" / "dist"
DOC_PATH = ROOT / "docs" / "sources.md"
