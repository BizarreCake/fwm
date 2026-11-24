"""Worker that runs inside a QuantConnect research notebook.

`qcbridge worker` prints this file with a `start(...)` line appended; paste that
into one notebook cell and run it. The worker dials out to the proxy, runs each
snippet it is sent and sends the value of the snippet's last expression back.

A snippet can read everything the notebook has defined (so `qb` is available),
but what it assigns is thrown away afterwards unless the job asks to keep it:
variables left behind by earlier snippets are how a long-lived kernel runs out
of memory.

Standard library only, and no imports from this package: it has to run as a pasted cell.
"""
import ast
import contextlib
import gc
import hashlib
import hmac
import io
import json
import os
import socket
import struct
import threading
import traceback

NONCE = 16
MAC = 32
MAX_HEADER = 1 << 20
MAX_PAYLOAD = 4 << 30
RETRY_SECONDS = 2
IDLE_SECONDS = 300
# Encoding a frame holds the original, a cleaned copy and the parquet bytes at once.
RESULT_HEADROOM = 3


class WireError(Exception):
    pass


def _mac(key, *parts):
    return hmac.new(key, b"".join(parts), hashlib.sha256).digest()


def _read(sock, n):
    chunks = []
    while n:
        chunk = sock.recv(min(n, 1 << 20))
        if not chunk:
            raise WireError("connection closed")
        chunks.append(chunk)
        n -= len(chunk)
    return b"".join(chunks)


class Channel:
    """Authenticated frames over a socket: a JSON header plus a binary payload.

    Every frame carries an HMAC over its direction, sequence number and
    contents, so frames cannot be forged, replayed or reordered by anyone
    without the token. The contents are not encrypted.
    """

    def __init__(self, sock, key, role):
        self.sock = sock
        self.key = key
        self.out_tag, self.in_tag = (b"S", b"W") if role == "server" else (b"W", b"S")
        self.out_seq = self.in_seq = 0

    def send(self, header, payload=b""):
        head = json.dumps(header).encode()
        lengths = struct.pack(">IQ", len(head), len(payload))
        mac = _mac(self.key, self.out_tag, struct.pack(">Q", self.out_seq), lengths, head, payload)
        self.out_seq += 1
        self.sock.sendall(lengths + head + payload + mac)

    def recv(self):
        lengths = _read(self.sock, 12)
        head_len, payload_len = struct.unpack(">IQ", lengths)
        if head_len > MAX_HEADER or payload_len > MAX_PAYLOAD:
            raise WireError("frame too large")
        head = _read(self.sock, head_len)
        payload = _read(self.sock, payload_len)
        mac = _read(self.sock, MAC)
        want = _mac(self.key, self.in_tag, struct.pack(">Q", self.in_seq), lengths, head, payload)
        if not hmac.compare_digest(mac, want):
            raise WireError("bad frame signature")
        self.in_seq += 1
        return json.loads(head), payload


def handshake_server(sock, token):
    """Prove we hold the token and check the worker does. Returns a Channel."""
    secret = token.encode()
    nonce_s = os.urandom(NONCE)
    sock.sendall(nonce_s)
    reply = _read(sock, NONCE + MAC)
    nonce_w, proof = reply[:NONCE], reply[NONCE:]
    if not hmac.compare_digest(proof, _mac(secret, b"worker", nonce_s, nonce_w)):
        raise WireError("worker failed authentication")
    sock.sendall(_mac(secret, b"server", nonce_s, nonce_w))
    return Channel(sock, _mac(secret, b"session", nonce_s, nonce_w), "server")


def handshake_worker(sock, token):
    secret = token.encode()
    nonce_s = _read(sock, NONCE)
    nonce_w = os.urandom(NONCE)
    sock.sendall(nonce_w + _mac(secret, b"worker", nonce_s, nonce_w))
    proof = _read(sock, MAC)
    if not hmac.compare_digest(proof, _mac(secret, b"server", nonce_s, nonce_w)):
        raise WireError("server failed authentication")
    return Channel(sock, _mac(secret, b"session", nonce_s, nonce_w), "worker")


def _proc_bytes(path, key):
    try:
        with open(path) as lines:
            for line in lines:
                if line.startswith(key):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _cgroup_bytes(*paths):
    for path in paths:
        try:
            with open(path) as value:
                return int(value.read().strip())
        except (OSError, ValueError):
            pass
    return None


def memory():
    """Bytes the kernel process holds, and bytes used and allowed for the whole
    notebook container (the machine, if there is no container limit). None where unknown."""
    limit = _cgroup_bytes("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes")
    used = _cgroup_bytes("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes")
    total = _proc_bytes("/proc/meminfo", "MemTotal:")
    available = _proc_bytes("/proc/meminfo", "MemAvailable:")
    if limit is None or used is None or (total is not None and limit > total):
        limit = total
        used = total - available if total is not None and available is not None else None
    return {"kernel": _proc_bytes("/proc/self/status", "VmRSS:"), "used": used, "limit": limit}


def _size(count):
    return "%.1f GB" % (count / 1e9) if count >= 1e9 else "%.0f MB" % (count / 1e6)


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def encode(value):
    """Turn a snippet's result into (kind, bytes)."""
    if value is None:
        return "none", b""
    try:
        import pandas as pd
    except ImportError:
        pd = None
    if pd is not None and isinstance(value, pd.Series):
        value = value.to_frame(name=value.name if value.name is not None else "value")
    if pd is not None and isinstance(value, pd.DataFrame):
        size = int(value.memory_usage(deep=True).sum())
        usage = memory()
        if usage["limit"] is not None and usage["used"] is not None:
            free = usage["limit"] - usage["used"]
            if size * RESULT_HEADROOM > free:
                raise MemoryError(
                    "The result is %s in memory and sending it takes about %d times that, but the notebook has "
                    "only %s free. Return fewer rows or columns, or split the request."
                    % (_size(size), RESULT_HEADROOM, _size(free))
                )
        frame = value if isinstance(value.index, pd.RangeIndex) else value.reset_index()
        frame = frame.copy()
        frame.columns = [str(column) for column in frame.columns]
        for column in frame.columns:
            # QuantConnect puts Symbol objects in indexes; parquet needs plain values.
            if frame[column].dtype == object:
                frame[column] = frame[column].map(_plain)
        try:
            buffer = io.BytesIO()
            frame.to_parquet(buffer, index=False)
            return "parquet", buffer.getvalue()
        except Exception:
            return "csv", frame.to_csv(index=False).encode()
    try:
        return "json", json.dumps(value).encode()
    except (TypeError, ValueError):
        return "text", repr(value).encode()


def execute(code, namespace, keep=False):
    """Run a snippet; return (header, payload) describing its last expression.

    Unless keep is set the snippet runs in a copy of the namespace, so it sees
    the notebook's variables but its own are released when it finishes.
    """
    out = io.StringIO()
    scope = namespace if keep else dict(namespace)
    value = None
    try:
        tree = ast.parse(code, "<snippet>")
        last = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last = ast.Expression(tree.body.pop().value)
        with contextlib.redirect_stdout(out):
            exec(compile(tree, "<snippet>", "exec"), scope)
            value = eval(compile(last, "<snippet>", "eval"), scope) if last else None
        kind, payload = encode(value)
        header = {"ok": True, "kind": kind}
    except BaseException:
        header, payload = {"ok": False, "error": traceback.format_exc()}, b""
    value = scope = None
    gc.collect()
    header["stdout"] = out.getvalue()
    header["memory"] = memory()
    return header, payload


def ensure_quantbook(namespace):
    """Give the notebook one shared `qb` if it has QuantConnect loaded but no QuantBook yet,
    so snippets do not each build their own."""
    if "qb" not in namespace and "QuantBook" in namespace:
        namespace["qb"] = namespace["QuantBook"]()


class Worker:
    def __init__(self, host, port, token, namespace):
        self.host, self.port, self.token, self.namespace = host, port, token, namespace
        self.stopped = threading.Event()
        self.jobs = 0
        self.thread = threading.Thread(target=self._loop, name="qcbridge-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()

    def _loop(self):
        while not self.stopped.is_set():
            try:
                self._session()
            except (OSError, WireError, ValueError):
                pass
            self.stopped.wait(RETRY_SECONDS)

    def _session(self):
        with socket.create_connection((self.host, self.port), timeout=10) as sock:
            channel = handshake_worker(sock, self.token)
            sock.settimeout(IDLE_SECONDS)
            while not self.stopped.is_set():
                header, _ = channel.recv()
                if header.get("op") != "run":
                    raise WireError("unknown request")
                try:
                    ensure_quantbook(self.namespace)
                except Exception:
                    pass  # the snippet will report the missing qb itself
                result, payload = execute(header["code"], self.namespace, header.get("keep", False))
                self.jobs += 1
                channel.send(result, payload)
                del result, payload


def start(host, port, token, namespace=None):
    """Start the worker in a background thread, replacing any earlier one."""
    previous = globals().get("_worker")
    if previous is not None:
        previous.stop()
    if namespace is None:
        try:
            namespace = get_ipython().user_ns  # noqa: F821 (defined inside Jupyter)
        except NameError:
            namespace = globals()
    worker = Worker(host, port, token, namespace)
    globals()["_worker"] = worker
    print("qcbridge worker running; it will connect to %s:%s whenever a job is sent. stop() ends it." % (host, port))
    return worker


def stop():
    worker = globals().get("_worker")
    if worker is not None:
        worker.stop()
