from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fwm.sources import DB_PATH, ROOT


def main() -> None:
    parser = argparse.ArgumentParser(prog="fwm")
    sub = parser.add_subparsers(dest="command", required=True)

    from fwm import sources

    ingest = sub.add_parser("ingest", help="Download every source and load it into DuckDB")
    ingest.add_argument("--no-download", action="store_true", help="Reuse the files already in data/raw")
    ingest.add_argument("--only", choices=sources.names(), help="Refresh one group of sources, or one source, instead of all")

    sub.add_parser("status", help="Show what is loaded from each source and whether newer data has probably been published")

    describe = sub.add_parser("sources", help="Print the description of every source and table (docs/sources.md)")
    describe.add_argument("--write", action="store_true", help="Write it to docs/sources.md")

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
        for source in sources.selected(args.only):
            print(sources.load(source, download=not args.no_download))
    elif args.command == "status":
        import duckdb

        con = duckdb.connect(str(DB_PATH), read_only=True)
        rows = sources.status(con)
        print(f"{'Release':58} {'Latest':11} {'Loaded on':11} {'Next usually out':17} State")
        for row in rows:
            print(f"{row['what'][:57]:58} {row['latest'] or '-':11} {row['loaded_on'] or '-':11} {row['next_due'] or '-':17} {row['state']}")
        stale = list(dict.fromkeys(row["refresh"] for row in rows if row["state"] != "current"))
        if stale:
            print("\nTo refresh:\n" + "\n".join(f"  {command}" for command in stale))
        leftover = sources.unregistered(con)
        if leftover:
            print(f"\nRelease rows no source claims (reload their source to clear them): {', '.join(leftover)}")
    elif args.command == "sources":
        if args.write:
            sources.DOC_PATH.write_text(sources.render(), encoding="utf-8")
            print(f"Wrote {sources.DOC_PATH}")
        else:
            print(sources.render())
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
