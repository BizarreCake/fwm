import { useEffect, useRef, useState } from "react";
import { Markdown } from "./Markdown";
import { useFetch } from "./useFetch";

type Part =
  | { kind: "text"; text: string }
  | { kind: "tool"; label: string; link: string | null; ok: boolean }
  | { kind: "gap"; category: string; explanation: string };

type Item =
  | { role: "user"; text: string }
  | { role: "assistant"; parts: Part[]; status: "streaming" | "done" | "error"; error?: string; model?: string };

interface Status {
  configured: boolean;
  /** The model the assistant is set to use, e.g. "Claude Opus 5.5", and how it is reached. */
  model_name: string;
  via: string | null;
  hint: string | null;
}

const SUGGESTIONS = [
  "Who holds US Treasuries, and how has that changed since 2022?",
  "What stood out in the latest quarter?",
  "How has the Fed's balance sheet changed since it began runoff?",
  "Where do money market funds put their money?",
];

const GAP_TITLE: Record<string, string> = {
  counterparty: "The data does not record who holds whose paper",
  entity: "The data has sectors, not individual names",
  frequency: "The data is quarterly",
  causation: "The data does not say why",
  detail: "The data does not break this out",
  forecast: "The data does not look ahead",
  coverage: "Outside what this data covers",
};

function newSession(): string {
  return crypto.randomUUID();
}

/** Parse a server-sent event stream into JSON events. */
async function* events(response: Response): AsyncGenerator<Record<string, any>> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      if (chunk.startsWith("data: ")) yield JSON.parse(chunk.slice(6));
    }
  }
}

export function Chat() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const session = useRef(newSession());
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const status = useFetch<Status>("/api/chat/status").data;

  useEffect(() => {
    document.body.classList.toggle("chat-open", open);
    if (open) input.current?.focus();
  }, [open]);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [items]);

  const update = (change: (item: Extract<Item, { role: "assistant" }>) => void) =>
    setItems((current) => {
      const next = [...current];
      const last = next[next.length - 1];
      if (last?.role !== "assistant") return current;
      const copy = { ...last, parts: last.parts.map((p) => ({ ...p })) };
      change(copy);
      next[next.length - 1] = copy;
      return next;
    });

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy) return;
    setDraft("");
    setBusy(true);
    setItems((current) => [...current, { role: "user", text: message }, { role: "assistant", parts: [], status: "streaming" }]);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.current, message }),
      });
      if (!response.ok || !response.body) throw new Error(`The server returned ${response.status}.`);
      let fresh = true; // whether the next text starts a new part
      for await (const event of events(response)) {
        if (event.type === "text") {
          const startNew = fresh;
          fresh = false;
          update((item) => {
            const last = item.parts[item.parts.length - 1];
            if (!startNew && last?.kind === "text") last.text += event.text;
            else item.parts.push({ kind: "text", text: event.text });
          });
        } else if (event.type === "tool") {
          fresh = true;
          update((item) => item.parts.push({ kind: "tool", label: event.label, link: event.link, ok: event.ok }));
        } else if (event.type === "gap") {
          fresh = true;
          update((item) => item.parts.push({ kind: "gap", category: event.category, explanation: event.explanation }));
        } else if (event.type === "break") {
          fresh = true;
        } else if (event.type === "error") {
          update((item) => {
            item.status = "error";
            item.error = event.message;
          });
        } else if (event.type === "done") {
          update((item) => {
            item.status = "done";
            item.model = event.model_name;
          });
        }
      }
      update((item) => {
        if (item.status === "streaming") item.status = "done";
      });
    } catch (e) {
      update((item) => {
        item.status = "error";
        item.error = e instanceof Error ? e.message : String(e);
      });
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    session.current = newSession();
    setItems([]);
    input.current?.focus();
  };

  if (!open) {
    return (
      <button className="chat-launch" onClick={() => setOpen(true)}>
        Ask a question
      </button>
    );
  }

  const unavailable = status !== null && !status.configured;

  return (
    <aside className="chat" aria-label="Ask about the data">
      <header className="chat-head">
        <div>
          <h2>Ask about the data</h2>
          {status?.configured && (
            <p className="chat-model" title="The model that answers questions here">
              {status.model_name}
              {status.via && <> · via {status.via}</>}
            </p>
          )}
        </div>
        <div>
          {items.length > 0 && (
            <button onClick={reset} disabled={busy}>
              New conversation
            </button>
          )}
          <button onClick={() => setOpen(false)} aria-label="Close the assistant">
            ✕
          </button>
        </div>
      </header>

      <div className="chat-log" ref={log} aria-live="polite">
        {items.length === 0 && (
          <div className="chat-empty">
            <p className="muted">
              Answers come from the accounts on these pages, with links to the numbers behind them. It will say when the data cannot answer
              something.
            </p>
            {SUGGESTIONS.map((suggestion) => (
              <button key={suggestion} className="chat-suggestion" disabled={unavailable} onClick={() => send(suggestion)}>
                {suggestion}
              </button>
            ))}
          </div>
        )}
        {items.map((item, i) =>
          item.role === "user" ? (
            <div key={i} className="chat-user">
              {item.text}
            </div>
          ) : (
            <div key={i} className="chat-assistant">
              {item.parts.map((part, k) => {
                if (part.kind === "text") return <Markdown key={k} text={part.text} />;
                if (part.kind === "gap")
                  return (
                    <div key={k} className="chat-gap">
                      <strong>{GAP_TITLE[part.category] ?? "A limit of the data"}</strong>
                      <span>{part.explanation}</span>
                    </div>
                  );
                return (
                  <div key={k} className="chat-tool">
                    {part.ok ? "Looked up" : "Could not look up"}{" "}
                    {part.link ? <a href={part.link}>{part.label}</a> : <span>{part.label}</span>}
                  </div>
                );
              })}
              {item.status === "done" && item.model && <div className="chat-working">Answered by {item.model}</div>}
              {item.status === "streaming" && <div className="chat-working">{item.parts.length ? "Working…" : "Thinking…"}</div>}
              {item.status === "error" && (
                <div className="chat-error" role="alert">
                  {item.error}
                </div>
              )}
            </div>
          ),
        )}
      </div>

      {unavailable && (
        <p className="chat-error" role="status">
          {status.hint}
        </p>
      )}
      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <textarea
          ref={input}
          value={draft}
          rows={2}
          placeholder="Ask about holders, flows, sectors, rates…"
          aria-label="Your question"
          disabled={unavailable}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(draft);
            }
          }}
        />
        <button type="submit" className="chat-send" disabled={busy || unavailable || !draft.trim()}>
          {busy ? "Answering…" : "Ask"}
        </button>
      </form>
    </aside>
  );
}
