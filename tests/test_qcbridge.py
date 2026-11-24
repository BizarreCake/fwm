"""The QuantConnect bridge, exercised over loopback with the worker in a thread."""
import json
import socket

import pytest

import qcbridge as qc
from qcbridge import worker as qc_worker


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(qc_worker, "RETRY_SECONDS", 0.05)
    workers = {}
    namespace = {}  # stands in for the notebook's variables, shared by every snippet in a test
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]

        def run(code, worker_token="secret", wait=5, keep=False):
            if worker_token not in workers:
                workers[worker_token] = qc_worker.Worker("127.0.0.1", port, worker_token, namespace)
            return qc.exchange(listener, "secret", code, wait=wait, timeout=5, keep=keep)

        run.namespace = namespace
        yield run
    for worker in workers.values():
        worker.stop()


def test_returns_last_expression_and_stdout(bridge):
    result = bridge("x = 20\nprint('hello')\n{'answer': x + 22}")
    assert result.kind == "json"
    assert json.loads(result.data) == {"answer": 42}
    assert result.stdout == "hello\n"


def test_no_trailing_expression_returns_nothing(bridge):
    assert bridge("x = 1").kind == "none"


def test_snippet_error_carries_the_traceback(bridge):
    with pytest.raises(qc.QCError, match="ZeroDivisionError"):
        bridge("1 / 0")


def test_worker_with_wrong_token_is_rejected(bridge):
    with pytest.raises(qc.QCError, match="No worker connected"):
        bridge("1", worker_token="wrong", wait=1)


def test_snippet_variables_are_discarded_unless_kept(bridge):
    bridge.namespace["notebook_value"] = 7
    assert json.loads(bridge("mine = notebook_value * 2\nmine").data) == 14
    assert "mine" not in bridge.namespace
    with pytest.raises(qc.QCError, match="NameError"):
        bridge("mine")
    bridge("mine = 3", keep=True)
    assert json.loads(bridge("mine + notebook_value").data) == 10


def test_quantbook_is_created_once_for_all_snippets(bridge):
    bridge.namespace["QuantBook"] = lambda: object()
    first = json.loads(bridge("id(qb)").data)
    assert json.loads(bridge("id(qb)").data) == first == id(bridge.namespace["qb"])


def test_result_reports_notebook_memory(bridge, monkeypatch):
    monkeypatch.setattr(qc_worker, "memory", lambda: {"kernel": 6e8, "used": 9e9, "limit": 11e9})
    result = bridge("1")
    assert qc.memory_report(result.memory) == ("Notebook memory: 9.0 GB of 11.0 GB used (kernel 0.6 GB)", True)
    assert qc.memory_report({"kernel": None, "used": None, "limit": None}) == ("", False)


def test_frame_too_large_for_the_notebook_is_refused(bridge, monkeypatch):
    pytest.importorskip("pandas")
    monkeypatch.setattr(qc_worker, "memory", lambda: {"kernel": 1, "used": 10_000_000_000, "limit": 10_000_001_000})
    with pytest.raises(qc.QCError, match="Return fewer rows or columns"):
        bridge("import pandas as pd\npd.DataFrame({'x': range(1000)})")
    assert json.loads(bridge("1").data) == 1  # the worker is still usable afterwards


def test_dataframe_comes_back_as_parquet(bridge):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    import io

    result = bridge(
        "import pandas as pd\n"
        "class Symbol:\n"
        "    def __str__(self): return 'SPY'\n"
        "index = pd.MultiIndex.from_tuples([(Symbol(), pd.Timestamp('2024-01-02'))], names=['symbol', 'time'])\n"
        "pd.DataFrame({'close': [472.65]}, index=index)"
    )
    assert result.kind == "parquet"
    frame = pd.read_parquet(io.BytesIO(result.data))
    assert frame.to_dict("records") == [{"symbol": "SPY", "time": pd.Timestamp("2024-01-02"), "close": 472.65}]


def test_worker_cell_is_self_contained(tmp_path, monkeypatch):
    monkeypatch.setattr(qc, "TOKEN_PATH", tmp_path / "token")
    cell = qc.worker_cell()
    compile(cell, "<cell>", "exec")
    assert "qcbridge" not in [line.split()[1].split(".")[0] for line in cell.splitlines() if line.startswith(("import ", "from "))]
    assert f"start('proxy.jacobzh.com', {qc.PORT}, '{(tmp_path / 'token').read_text()}')" in cell
