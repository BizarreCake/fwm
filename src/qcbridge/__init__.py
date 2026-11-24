"""Run code snippets in a QuantConnect research notebook and fetch the result.

The notebook runs the worker from `worker.py`, which dials out to a proxy
host. Each `run()` opens a reverse SSH tunnel from that proxy back to a local
listener, hands the snippet to the worker when it connects, and returns what
the snippet's last expression evaluated to.
"""
from __future__ import annotations

import contextlib
import os
import secrets
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from qcbridge import worker

ROOT = Path(__file__).resolve().parents[2]

PROXY = os.environ.get("FWM_QC_PROXY", "ec2-user@proxy.jacobzh.com")
PORT = int(os.environ.get("FWM_QC_PORT", "9997"))
KEY_PATH = Path(os.environ.get("FWM_QC_KEY", ROOT / "keys" / "proxy.pem"))
TOKEN_PATH = ROOT / "keys" / "qc_token"

EXTENSIONS = {"parquet": ".parquet", "csv": ".csv", "json": ".json", "text": ".txt"}


MEMORY_WARNING = 0.8  # warn when the notebook has used this share of its memory


def memory_report(memory: dict | None) -> tuple[str, bool]:
    """A one-line summary of the notebook's memory, and whether it is running short."""
    if not memory or memory.get("used") is None or not memory.get("limit"):
        return "", False
    gb = lambda count: f"{count / 1e9:.1f} GB"
    kernel = f" (kernel {gb(memory['kernel'])})" if memory.get("kernel") else ""
    text = f"Notebook memory: {gb(memory['used'])} of {gb(memory['limit'])} used{kernel}"
    return text, memory["used"] / memory["limit"] >= MEMORY_WARNING


class QCError(Exception):
    pass


@dataclass
class Result:
    kind: str  # parquet, csv, json, text or none
    data: bytes
    stdout: str
    memory: dict | None = None  # bytes: kernel, used, limit (see worker.memory)


def token() -> str:
    """The secret shared with the worker; created on first use."""
    if not TOKEN_PATH.exists():
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.touch(mode=0o600)
        TOKEN_PATH.write_text(secrets.token_urlsafe(32))
    return TOKEN_PATH.read_text().strip()


def worker_cell() -> str:
    """The notebook cell to paste into QuantConnect: the worker plus its start line."""
    source = Path(worker.__file__).read_text()
    host = PROXY.rsplit("@", 1)[-1]
    return f"{source}\n\nstart({host!r}, {PORT}, {token()!r})\n"


@contextlib.contextmanager
def tunnel(local_port: int):
    """Forward PORT on the proxy to local_port here for the duration of the block."""
    process = subprocess.Popen(
        [
            "ssh", "-N", "-i", str(KEY_PATH),
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15",
            "-o", "StrictHostKeyChecking=accept-new",
            "-R", f"0.0.0.0:{PORT}:127.0.0.1:{local_port}",
            PROXY,
        ],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )

    def check() -> None:
        if process.poll() is not None:
            raise QCError(f"SSH tunnel to {PROXY} failed: {process.stderr.read().strip() or 'ssh exited'}")

    try:
        yield check
    finally:
        process.terminate()
        process.wait(timeout=10)


def exchange(listener: socket.socket, secret: str, code: str, wait: float, timeout: float, check=lambda: None, keep: bool = False) -> Result:
    """Wait for the worker to connect to listener, send it code, return its result.

    Connections that fail authentication (the proxy port is public) are dropped.
    """
    deadline = time.monotonic() + wait
    listener.settimeout(0.5)
    while True:
        check()
        if time.monotonic() > deadline:
            raise QCError(
                f"No worker connected within {wait:.0f}s. Is the notebook open with the worker cell running? "
                "(`qcbridge worker` prints the cell.)"
            )
        try:
            conn, _ = listener.accept()
        except socket.timeout:
            continue
        try:
            conn.settimeout(5)
            channel = worker.handshake_server(conn, secret)
        except (OSError, worker.WireError):
            conn.close()
            continue
        break
    with conn:
        try:
            conn.settimeout(timeout)
            channel.send({"op": "run", "code": code, "keep": keep})
            header, payload = channel.recv()
        except socket.timeout:
            raise QCError(f"The snippet did not finish within {timeout:.0f}s") from None
        except (OSError, worker.WireError) as error:
            raise QCError(f"Lost the worker while it was running the snippet: {error}") from None
    if not header["ok"]:
        raise QCError(f"The snippet failed in the notebook:\n{header['stdout']}{header['error']}")
    return Result(header["kind"], payload, header["stdout"], header.get("memory"))


def run(code: str, wait: float = 60, timeout: float = 900, keep: bool = False) -> Result:
    """Run code in the QuantConnect notebook and return its last expression.

    The snippet's variables are discarded afterwards unless keep is set.
    """
    if not KEY_PATH.exists():
        raise QCError(f"SSH key not found at {KEY_PATH}")
    secret = token()
    with socket.create_server(("127.0.0.1", 0)) as listener:
        with tunnel(listener.getsockname()[1]) as check:
            return exchange(listener, secret, code, wait, timeout, check, keep)
