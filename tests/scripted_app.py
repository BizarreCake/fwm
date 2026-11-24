"""The real app with a scripted model behind the chat endpoint, for the browser tests."""

from scripted import ScriptedClient, call

from fwm import api


def respond(messages):
    last = messages[-1]
    if isinstance(last["content"], str):  # a new question from the user
        if "JPMorgan" in last["content"]:
            return [call("g1", "flag_data_gap", category="entity", explanation="There are no individual banks in the accounts.")], "tool_use"
        return [call("t1", "get_instrument", instrument_id="F3_2", period="2022:Q1")], "tool_use"
    if "flag_data_gap" in str(messages[-2]["content"]):
        return [{"type": "text", "text": "The accounts cover the banking sector as a whole, not single banks."}], "end_turn"
    turns = sum(1 for m in messages if isinstance(m["content"], str))
    text = (f"Answer {turns}: **Foreign investors** held the most in Q1 2022 (`LM263061105.Q`).\n\n"
            "- See [Treasury holders](#/us/instrument/F3_2?period=2022:Q1)\n- And [a bad link](javascript:alert(1))")
    return [{"type": "text", "text": text}], "end_turn"


api._client = ScriptedClient(respond)
app = api.app
