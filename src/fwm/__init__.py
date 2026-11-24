from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_Z1 = ROOT / "data" / "raw" / "z1"
RAW_H15 = ROOT / "data" / "raw" / "h15"
DB_PATH = ROOT / "data" / "fwm.duckdb"


def main() -> None:
    parser = argparse.ArgumentParser(prog="fwm")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Download the Z.1 accounts and H.15 interest rates and load them into DuckDB")
    ingest.add_argument("--no-download", action="store_true", help="Reuse the files already in data/raw")
    ingest.add_argument("--only", choices=["z1", "rates"], help="Refresh one source instead of both")

    serve = sub.add_parser("serve", help="Run the API (and the built UI, if web/dist exists)")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args()

    if args.command == "ingest":
        from fwm import rates, z1

        if args.only != "rates":
            if not args.no_download:
                published = z1.download(RAW_Z1)
                print(f"Downloaded Z.1 release (published {published})")
            z1.archive(RAW_Z1)
            summary = z1.ingest(RAW_Z1, DB_PATH)
            print(f"Loaded {summary['observations']:,} observations across {summary['series']:,} series; "
                  f"latest quarter {summary['latest_period']}")
        if args.only != "z1":
            if not args.no_download:
                rates.download(RAW_H15)
            summary = rates.ingest(RAW_H15, DB_PATH)
            print(f"Loaded {summary['observations']:,} daily interest rates; latest {summary['latest']}")
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("fwm.api:app", host="127.0.0.1", port=args.port, reload=args.reload)
