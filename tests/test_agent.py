"""The agent's tools against the data, and the agent loop and benchmark grader against a scripted model.

Nothing here calls the Anthropic API. `uv run fwm bench` does that.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from scripted import ScriptedClient, call

from fwm import agent, bench, instruments, sectors, tools

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield connection
    finally:
        connection.close()


# ---- tools -----------------------------------------------------------------------

def test_instrument_tool_matches_the_instrument_page(con):
    page = instruments.view(con, "F3_2")
    result = tools.get_instrument(con, "F3_2")
    assert result["period"] == page["periods"][-1]
    assert result["holders"]["total"]["amount"] == pytest.approx(page["holders"]["level"][-1] / 1000, abs=0.05)
    for group in result["holders"]["groups"]:
        source = next(g for g in page["holders"]["groups"] if g["id"] == group["group_id"])
        assert group["amount"] == pytest.approx(source["level"][-1] / 1000, abs=0.05)
    assert sum(g["share_pct"] for g in result["holders"]["groups"]) == pytest.approx(100, abs=0.5)


def test_change_between_quarters_splits_into_transactions_and_valuation(con):
    result = tools.get_instrument(con, "F51_1", "2026:Q2", "2024:Q2")
    assert result["compared_to"] == "2024:Q2"
    for group in result["holders"]["groups"]:
        change = group["change"]
        assert change["change_in_amount"] == pytest.approx(group["amount"] - change["amount_at_start"], abs=0.2)
        assert change["net_transactions"] + change["valuation_and_other"] == pytest.approx(change["change_in_amount"], abs=0.2)


def test_sector_tool_lines_roll_up(con):
    result = tools.get_sector(con, "S121")
    page = sectors.balance_sheet(con, "S121")
    assert result["assets"]["total"]["amount"] == pytest.approx(page["assets"]["level"][-1] / 1000, abs=0.05)
    top = [line for line in result["assets"]["lines"] if line["depth"] == 0]
    assert sum(line["amount"] for line in top) == pytest.approx(result["assets"]["total"]["amount"], abs=0.5)


def test_history_flows_reconcile_with_levels(con):
    series = tools.get_instrument(con, "F3_2")["holders"]["groups"][0]["sectors"][0]["series"]
    for frequency in ("quarterly", "annual"):
        rows = tools.get_history(con, [series], "2015:Q4", "2025:Q4", frequency)["series"][0]["observations"]
        for before, after in zip(rows, rows[1:]):
            assert after["net_transactions"] + after["valuation_and_other"] == pytest.approx(after["amount"] - before["amount"], abs=0.3)


def test_every_tool_runs_with_minimal_arguments_and_stays_small(con):
    series = tools.get_instrument(con, "F3_2")["holders"]["total"]["series"]
    minimal = {"get_instrument": {"instrument_id": "F3_2"}, "get_sector": {"sector_id": "S1M"},
               "get_history": {"series": [series]}, "latest_moves": {"kind": "largest_flows"},
               "get_fed_weekly_history": {"lines": ["reserves"]},
               "get_foreign_holder_history": {"countries": ["Japan"]}, "get_country": {"country": "Japan"},
               "flag_data_gap": {"category": "entity", "explanation": "x"}}
    for name in tools.REGISTRY:
        result = tools.run(con, name, minimal.get(name, {}))
        assert len(json.dumps(result)) < 40_000, name


def test_weekly_fed_tool_matches_the_weekly_page(con):
    from fwm import fedweekly

    view = fedweekly.view(con)
    sheet = tools.get_fed_weekly(con)
    assert sheet["date"] == view["periods"][-1] and sheet["link"] == f"#/us/weekly/fed?period={sheet['date']}"
    assert sheet["compare_to"] == view["periods"][view["quarterly"]["index"]]
    top = lambda rows: sum(row["amount"] for row in rows if "part_of" not in row)
    assert top(sheet["assets"]) == pytest.approx(sheet["total_assets"]["amount"], abs=0.5)
    assert top(sheet["liabilities_and_capital"]) == pytest.approx(sheet["total_assets"]["amount"], abs=0.5)
    reserves = next(row for row in sheet["liabilities_and_capital"] if row["line"] == "reserves")
    assert reserves["series"] == ["H.4.1 RESPPLLDD"]

    # A quarter means its last week; a date means the latest week on or before it.
    assert tools.get_fed_weekly(con, "2026:Q2")["date"] == sheet["compare_to"]
    assert tools.get_fed_weekly(con, "2020-03-17")["date"] == "2020-03-11"

    history = tools.get_fed_weekly_history(con, ["reserves", "total_assets"], "2008-01-02", frequency="quarterly")
    assert history["dates"][-1] == sheet["date"] and len(history["dates"]) < 80
    assert history["lines"][0]["amounts"][-1] == reserves["amount"]
    assert history["lines"][1]["highest_week"]["date"].startswith("2022")
    with pytest.raises(tools.ToolError):
        tools.get_fed_weekly(con, "1999-01-01")
    with pytest.raises(tools.ToolError):
        tools.get_fed_weekly_history(con, ["nonsense"])


def test_foreign_holder_tools_match_the_country_page(con):
    from fwm import tic

    view = tic.view(con)
    result = tools.get_foreign_holders(con, top=80)
    assert result["month"] == view["periods"][-1] and result["link"] == f"#/us/foreign/treasuries?period={result['month']}"
    assert result["official"]["amount"] + result["private"]["amount"] == pytest.approx(result["all_foreign_holders"]["amount"], abs=0.3)
    assert sum(r["amount"] for r in result["regions"]) == pytest.approx(result["all_foreign_holders"]["amount"], abs=0.5)
    amounts = [row["amount"] for row in result["countries"]]
    assert amounts == sorted(amounts, reverse=True) and result["countries"][0]["rank"] == 1
    assert any("custody" in caveat for caveat in result["caveats"])

    # A quarter means its last month, and that month's total is what Z.1 shows for the rest of the world.
    quarter = tools.get_foreign_holders(con, month="2025:Q4")
    assert quarter["month"] == "2025-12"
    z1 = next(g for g in tools.get_instrument(con, "F3_2", "2025:Q4")["holders"]["groups"] if g["group_id"] == "row")
    assert quarter["all_foreign_holders"]["amount"] == pytest.approx(z1["amount"], rel=0.005)

    history = tools.get_foreign_holder_history(con, ["China", "total"], start="2020-01")
    assert history["holders"][0]["name"] == "China, Mainland" and history["months"][0] == "2020-01"
    assert history["holders"][0]["net_purchases_over_window"] is None  # purchases are not reported before 2023
    assert tools.get_foreign_holder_history(con, ["Japan"], start="2025-09")["holders"][0]["net_purchases_over_window"] is not None
    # Other securities: no bills, a link to their own page, and the nearest Z.1 line alongside.
    equities = tools.get_foreign_holders(con, "equities", month="2026:Q2")
    assert equities["link"] == "#/us/foreign/equities?period=2026-06" and "bills" not in equities["countries"][0]
    assert equities["quarterly_accounts"]["instrument_id"] == "F51_1"
    assert equities["all_foreign_holders"]["amount"] > equities["quarterly_accounts"]["rest_of_world_amount_that_quarter"]
    assert tools.get_foreign_holder_history(con, ["Japan"], "corporate")["link"].startswith("#/us/foreign/corporate")
    with pytest.raises(tools.ToolError):
        tools.get_foreign_holders(con, "gold")

    # Through the same entry point the model uses, with every optional argument.
    assert len(tools.run(con, "get_foreign_holders", {"month": "2026-06", "compare_to": "2025-06", "top": 5})["countries"]) == 5
    with pytest.raises(tools.ToolError):
        tools.run(con, "get_foreign_holders", {"top": "five"})
    with pytest.raises(tools.ToolError):
        tools.get_foreign_holders(con, month="2019-12")
    with pytest.raises(tools.ToolError):
        tools.get_foreign_holder_history(con, ["Atlantis"])


def test_bad_arguments_are_explained_not_raised_as_crashes(con):
    for name, arguments in [("get_instrument", {"instrument_id": "NOPE"}), ("get_instrument", {"instrument_id": "F3_2", "period": "soon"}),
                            ("get_instrument", {"instrument_id": "F3_2", "period": "2020:Q1", "compare_to": "2021:Q1"}),
                            ("get_sector", {"sector": "S121"}), ("get_history", {"series": []}),
                            ("latest_moves", {"kind": "biggest"}), ("no_such_tool", {}), ("get_sector", "S121")]:
        with pytest.raises(tools.ToolError):
            tools.run(con, name, arguments)


def test_tool_definitions_are_strict_and_stable():
    definitions = tools.definitions()
    assert definitions == tools.definitions()
    for definition in definitions:
        assert definition["strict"] and definition["input_schema"]["additionalProperties"] is False
        assert set(definition["input_schema"]["required"]) <= set(definition["input_schema"]["properties"])


# ---- the loop, with a scripted model ----------------------------------------------

def test_turn_runs_tools_and_returns_all_results_in_one_message(con):
    client = ScriptedClient([
        ([call("a", "get_instrument", instrument_id="F3_2"), call("b", "get_sector", sector_id="NOPE")], "tool_use"),
        ([{"type": "text", "text": "Foreign investors hold the most."}], "end_turn"),
    ])
    messages: list = []
    events = list(agent.run_turn(con, client, messages, "Who holds Treasuries?"))

    kinds = [event["type"] for event in events]
    assert kinds[:4] == ["tool", "break", "tool", "break"] and kinds[-1] == "done"
    assert set(kinds[4:-1]) == {"text"}
    assert "".join(event["text"] for event in events if event["type"] == "text") == "Foreign investors hold the most."
    assert events[0]["ok"] and events[0]["link"].startswith("#/us/instrument/F3_2") and "Treasury securities" in events[0]["label"]
    assert not events[2]["ok"]

    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    results = messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert "is_error" not in results[0] and results[1]["is_error"]
    assert "list_sectors" in results[1]["content"]

    first = client.requests[0]
    assert first["model"] == agent.MODEL and first["tools"] == tools.definitions()
    assert first["thinking"] == {"type": "adaptive"} and "temperature" not in first
    # The second request is the first plus what was appended: history is never rewritten.
    assert client.requests[1]["messages"][:1] == first["messages"]


def test_data_gap_is_reported_as_its_own_event(con):
    client = ScriptedClient([
        ([call("a", "flag_data_gap", category="entity", explanation="No single banks.")], "tool_use"),
        ([{"type": "text", "text": "The data has sectors only."}], "end_turn"),
    ])
    transcript = bench.Transcript.collect(agent.run_turn(con, client, [], "What does one bank hold?"))
    assert transcript.gaps == [{"category": "entity", "explanation": "No single banks."}]
    assert transcript.answer == "The data has sectors only."


def test_refusal_and_truncation_end_the_turn_without_running_tools(con):
    for stop_reason in ("refusal", "max_tokens"):
        client = ScriptedClient([([call("a", "get_instrument", instrument_id="F3_2")], stop_reason)])
        events = list(agent.run_turn(con, client, [], "q"))
        assert [event["type"] for event in events] == ["error"]


def test_missing_credentials_become_a_setup_message(con):
    class NoCredentials:
        beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **_: (_ for _ in ()).throw(
            TypeError("Could not resolve authentication method. Expected one of api_key, auth_token"))))
    events = list(agent.safe_turn(con, NoCredentials(), [], "q"))
    assert events == [{"type": "error", "message": agent.SETUP_HINT}]


def test_a_failed_turn_leaves_the_conversation_as_it_was(con):
    state = {"messages": [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "answer"}]}
    client = ScriptedClient([([call("a", "get_instrument", instrument_id="F3_2")], "max_tokens")])
    events = list(agent.answer(con, state, "q", client))
    assert events[-1]["type"] == "error" and len(state["messages"]) == 2


# ---- the benchmark grader ----------------------------------------------------------

def answer(text, calls=(), gaps=()):
    return bench.Transcript(answer=text, calls=list(calls), gaps=[{"category": g, "explanation": ""} for g in gaps])


def lookup(con, name, **arguments):
    return {"name": name, "input": arguments, "ok": True, "result": tools.run(con, name, arguments)}


def question(question_id):
    return next(q for q in bench.QUESTIONS if q.id == question_id)


def test_grader_accepts_a_correct_answer_and_rejects_wrong_ones(con):
    q = question("fed-treasury-level")
    found = lookup(con, "get_instrument", instrument_id="F3_2")
    fed = next(g for g in found["result"]["holders"]["groups"] if g["group_id"] == "fed")
    right = f"The Fed holds ${fed['amount'] / 1000:.2f} trillion of Treasuries (`{fed['sectors'][0]['series']}`). [Holders](#/us/instrument/F3_2)"
    assert bench.grade(q, answer(right, [found]), con) == []
    assert bench.grade(q, answer("The Fed holds $9.9 trillion of Treasuries.", [found]), con)
    assert any("no tool returned" in f for f in bench.grade(q, answer(right.replace(fed["sectors"][0]["series"], "LM999999999.Q"), [found]), con))
    assert any("does not exist" in f for f in bench.grade(q, answer(right.replace("F3_2)", "F9_9)"), [found]), con))
    assert any("without any successful lookup" in f for f in bench.grade(q, answer("The Fed holds $4.08 trillion."), con))
    assert any("flagged a data gap" in f for f in bench.grade(q, answer(right, [found], ["entity"]), con))


def test_grader_requires_the_right_gap_on_unanswerable_questions(con):
    q = question("named-bank")
    assert bench.grade(q, answer("The data has no individual banks.", gaps=["entity"]), con) == []
    assert bench.grade(q, answer("The data has no individual banks."), con)
    assert bench.grade(q, answer("JPMorgan holds about $300 billion.", gaps=["entity"]), con)


def test_benchmark_covers_all_three_kinds_with_unique_ids():
    ids = [q.id for q in bench.QUESTIONS]
    assert len(ids) == len(set(ids)) >= 20
    kinds = [q.kind for q in bench.QUESTIONS]
    assert kinds.count("answerable") >= 12 and kinds.count("partial") >= 3 and kinds.count("out_of_scope") >= 3
