from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_Z1 = ROOT / "data" / "raw" / "z1"
RAW_H15 = ROOT / "data" / "raw" / "h15"
RAW_H41 = ROOT / "data" / "raw" / "h41"
RAW_TIC = ROOT / "data" / "raw" / "tic"
RAW_ECB = ROOT / "data" / "raw" / "ecb"
DB_PATH = ROOT / "data" / "fwm.duckdb"


def main() -> None:
    parser = argparse.ArgumentParser(prog="fwm")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Download the Z.1 accounts, H.15 interest rates and H.4.1 weekly Fed balance sheet into DuckDB")
    ingest.add_argument("--no-download", action="store_true", help="Reuse the files already in data/raw")
    ingest.add_argument("--only", choices=["z1", "rates", "fed-weekly", "tic", "ecb"], help="Refresh one source instead of all")

    ask = sub.add_parser("ask", help="Ask the agent one question from the command line")
    ask.add_argument("question")

    bench = sub.add_parser("bench", help="Run the agent benchmark against the model (uses your Claude subscription or API credit)")
    bench.add_argument("--only", nargs="*", help="Question ids to run")
    bench.add_argument("--list", action="store_true", help="List the questions without running them")

    serve = sub.add_parser("serve", help="Run the API (and the built UI, if web/dist exists)")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args()

    if args.command == "ingest":
        from fwm import eacontext, ecb, euweekly, fedweekly, rates, tic, z1

        if args.only in (None, "z1"):
            if not args.no_download:
                published = z1.download(RAW_Z1)
                print(f"Downloaded Z.1 release (published {published})")
            z1.archive(RAW_Z1)
            summary = z1.ingest(RAW_Z1, DB_PATH)
            print(f"Loaded {summary['observations']:,} observations across {summary['series']:,} series; "
                  f"latest quarter {summary['latest_period']}")
        if args.only in (None, "rates"):
            if not args.no_download:
                rates.download(RAW_H15)
            summary = rates.ingest(RAW_H15, DB_PATH)
            print(f"Loaded {summary['observations']:,} daily interest rates; latest {summary['latest']}")
        if args.only in (None, "fed-weekly"):
            if not args.no_download:
                fedweekly.download(RAW_H41)
            summary = fedweekly.ingest(RAW_H41, DB_PATH)
            print(f"Loaded {summary['observations']:,} weekly Fed balance sheet values; latest {summary['latest']}")
        if args.only in (None, "tic"):
            if not args.no_download:
                tic.download(RAW_TIC)
            summary = tic.ingest(RAW_TIC, DB_PATH)
            print(f"Loaded foreign holdings of US securities for {summary['countries']} countries; latest {summary['latest']}")
        if args.only in (None, "ecb"):
            if not args.no_download:
                ecb.download(RAW_ECB)
                eacontext.download(RAW_ECB / "context")
                euweekly.download(RAW_ECB / "weekly")
            weekly_summary = euweekly.ingest(RAW_ECB / "weekly", DB_PATH)
            print(f"Loaded {weekly_summary['weeks']:,} weeks of the Eurosystem's balance sheet; latest {weekly_summary['latest']}")
            context_summary = eacontext.ingest(RAW_ECB / "context", DB_PATH)
            print(f"Loaded euro-area rates to {context_summary['rates_latest']}, GDP to {context_summary['gdp_latest']}, "
                  f"dollar exchange rate to {context_summary['fx_latest']}")
            summary = ecb.ingest(RAW_ECB, DB_PATH)
            print(f"Loaded {summary['observations']:,} euro-area observations in {summary['series']:,} series; latest {summary['latest']}")
    elif args.command in ("ask", "bench"):
        import json
        import time

        import duckdb

        from fwm import agent
        from fwm import bench as benchmark

        if args.command == "bench" and args.list:
            for question in benchmark.QUESTIONS:
                print(f"{question.id:34} {question.kind:13} {question.text}")
            return
        con = duckdb.connect(str(DB_PATH), read_only=True)
        print(f"Using {agent.describe()}", file=sys.stderr)
        if args.command == "ask":
            for event in agent.answer(con, {}, args.question):
                if event["type"] == "text":
                    print(event["text"], end="", flush=True)
                elif event["type"] == "tool":
                    print(f"\n  [{'looked up' if event['ok'] else 'failed'}: {event['label']}]", flush=True)
                elif event["type"] == "gap":
                    print(f"\n  [data gap, {event['category']}: {event['explanation']}]", flush=True)
                elif event["type"] == "error":
                    print(f"\nError: {event['message']}")
            print()
            return
        summary = benchmark.run(con, args.only)
        out = ROOT / "data" / "bench" / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2))
        print(f"\n{summary['passed']}/{summary['total']} passed ({summary['backend']}, effort {summary['effort']}). Details: {out}")
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("fwm.api:app", host="127.0.0.1", port=args.port, reload=args.reload)
