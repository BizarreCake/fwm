"""A stand-in for the Anthropic client, so the agent loop and the chat UI can be tested without the API."""

from types import SimpleNamespace


class ScriptedClient:
    """Replays prepared responses and records each request.

    `responses` is a list of (content blocks, stop_reason), or a function from the
    request's messages to one such pair.
    """

    def __init__(self, responses):
        self.responses = responses if callable(responses) else list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        content, stop_reason = self.responses(request["messages"]) if callable(self.responses) else self.responses.pop(0)
        message = SimpleNamespace(content=content, stop_reason=stop_reason, model="scripted",
                                  usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))
        events = []
        for block in content:
            if block["type"] == "text":
                text = block["text"]
                events += [SimpleNamespace(type="text", text=text[i:i + 17]) for i in range(0, len(text), 17)]

        class Stream:
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def __iter__(self): return iter(events)
            def get_final_message(self): return message
        return Stream()


def call(tool_id, name, **arguments):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": arguments}
