from __future__ import annotations

import argparse
import sys
from pathlib import Path

import qcbridge


def main() -> None:
    parser = argparse.ArgumentParser(prog="qcbridge", description="Run code in a QuantConnect research notebook and fetch the result")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("update", help="Replace the worker running in the notebook with this version, without re-pasting the cell")
    sub.add_parser("worker", help="Print the cell to paste into the QuantConnect notebook (once per notebook session)")
    run = sub.add_parser("run", help="Run a snippet in the notebook; its last expression is the result")
    run.add_argument("file", nargs="?", help="Snippet file, or - for stdin")
    run.add_argument("-c", "--code", help="Snippet given inline instead of as a file")
    run.add_argument("-o", "--out", type=Path, help="Where to save the result (default data/qc/<name>.<type>)")
    run.add_argument("--wait", type=float, default=60, help="Seconds to wait for the notebook worker to connect")
    run.add_argument("--keep", action="store_true", help="Leave the snippet's variables in the notebook for later snippets (they stay in memory)")
    run.add_argument("--timeout", type=float, default=900, help="Seconds to let the snippet run")
    args = parser.parse_args()

    if args.command == "worker":
        print(qcbridge.worker_cell())
        return
    if args.command == "update":
        try:
            result = qcbridge.run(qcbridge.worker_cell(), keep=True)
        except qcbridge.QCError as error:
            sys.exit(str(error))
        print(result.stdout, end="")
        return
    if (args.code is None) == (args.file is None):
        parser.error("give a snippet file (or - for stdin) or -c CODE, not both")
    if args.code is not None:
        code, name = args.code, "result"
    elif args.file == "-":
        code, name = sys.stdin.read(), "result"
    else:
        code, name = Path(args.file).read_text(), Path(args.file).stem
    try:
        result = qcbridge.run(code, wait=args.wait, timeout=args.timeout, keep=args.keep)
    except qcbridge.QCError as error:
        sys.exit(str(error))
    if result.stdout:
        print(result.stdout, end="", file=sys.stderr)
    if result.kind == "none":
        print("The snippet ran but did not end with an expression, so there is nothing to save.", file=sys.stderr)
    elif result.kind in ("json", "text") and args.out is None:
        print(result.data.decode())
    else:
        out = args.out or qcbridge.ROOT / "data" / "qc" / f"{name}{qcbridge.EXTENSIONS[result.kind]}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(result.data)
        print(f"Saved {out}{_describe(out) if result.kind == 'parquet' else ''}")
    report, short = qcbridge.memory_report(result.memory)
    if report:
        print(report, file=sys.stderr)
    if short:
        print("Warning: the notebook is close to its memory limit. Restart its kernel and run the worker cell again before large requests.", file=sys.stderr)


def _describe(path: Path) -> str:
    try:
        import duckdb
    except ImportError:
        return ""
    relation = duckdb.read_parquet(str(path))
    return f": {relation.count('*').fetchall()[0][0]:,} rows, columns {', '.join(relation.columns)}"
