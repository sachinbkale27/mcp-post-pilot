import { useEffect, useRef, useState, type FormEvent } from "react";
import Markdown from "react-markdown";
import { getMcpInfo, resetChat, streamChat, type AgentEvent, type McpInfo } from "./api";

type Step =
  | Exclude<AgentEvent, { type: "conversation" } | { type: "done" } | { type: "token" }>
  | { type: "text"; text: string };
interface Turn {
  user: string;
  steps: Step[];
  pending: boolean;
}

const EXAMPLES = [
  "What posts are on the blog?",
  "Write a short draft post about how MCP works, by sachin",
  "Publish the MCP post and show me its content",
  "Which posts are still drafts?",
];

export function App() {
  const [info, setInfo] = useState<McpInfo>();
  const [infoError, setInfoError] = useState<string>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string>();
  const bottom = useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.pending);

  useEffect(() => {
    getMcpInfo().then(setInfo).catch((e) => setInfoError(e.message));
  }, []);
  useEffect(() => {
    // Braces matter: an effect may only return a cleanup function, and scrollIntoView
    // returns a Promise in recent browsers.
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const updateLast = (fn: (t: Turn) => Turn) => setTurns((ts) => [...ts.slice(0, -1), fn(ts[ts.length - 1])]);

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput("");
    setTurns((ts) => [...ts, { user: text, steps: [], pending: true }]);
    try {
      for await (const event of streamChat(text, conversationId)) {
        if (event.type === "conversation") setConversationId(event.id);
        else if (event.type === "token") updateLast((t) => ({ ...t, steps: appendToken(t.steps, event.text) }));
        else if (event.type !== "done") updateLast((t) => ({ ...t, steps: [...t.steps, event] }));
      }
    } catch (e) {
      updateLast((t) => ({ ...t, steps: [...t.steps, { type: "error", message: (e as Error).message }] }));
    }
    updateLast((t) => ({ ...t, pending: false }));
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  async function newChat() {
    if (conversationId) await resetChat(conversationId);
    setConversationId(undefined);
    setTurns([]);
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <h2>MCP server</h2>
        {infoError && <p className="error">{infoError}</p>}
        {info && (
          <>
            <code className="url">{info.server_url}</code>
            <div className="desc">LLM: <code>{info.model}</code></div>
            <h3>Tools ({info.tools.length})</h3>
            <ul>
              {info.tools.map((t) => (
                <li key={t.name} title={t.description ?? ""}>
                  <code>{t.name}</code>
                  <div className="desc">{t.description?.split("\n")[0]}</div>
                </li>
              ))}
            </ul>
            <h3>Resources</h3>
            <ul>
              {[...info.resources, ...info.resource_templates].map((r) => (
                <li key={r}><code>{r}</code></li>
              ))}
            </ul>
            <h3>Prompts</h3>
            <ul>
              {info.prompts.map((p) => (
                <li key={p.name}><code>{p.name}</code></li>
              ))}
            </ul>
          </>
        )}
      </aside>

      <section className="chat">
        <header>
          <strong>LangGraph + MCP agent (OpenAI)</strong>
          <button className="secondary" onClick={newChat} disabled={busy}>New chat</button>
        </header>

        <div className="messages">
          {turns.length === 0 && (
            <div className="examples">
              <p>Ask the agent about the blog. Try:</p>
              {EXAMPLES.map((ex) => (
                <button key={ex} className="secondary" onClick={() => send(ex)}>{ex}</button>
              ))}
            </div>
          )}
          {turns.map((turn, i) => (
            <div key={i}>
              <div className="bubble user">{turn.user}</div>
              {turn.steps.map((step, j) => <StepView key={j} step={step} />)}
              {turn.pending && turn.steps[turn.steps.length - 1]?.type !== "text" && <div className="muted">Working…</div>}
            </div>
          ))}
          <div ref={bottom} />
        </div>

        <form className="composer" onSubmit={onSubmit}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about posts, or ask the agent to create / publish / delete one…"
            disabled={busy}
          />
          <button type="submit" disabled={busy || !input.trim()}>Send</button>
        </form>
      </section>
    </div>
  );
}

/** Append a streamed token to the current answer bubble, or start a new one after a tool step. */
function appendToken(steps: Step[], text: string): Step[] {
  const last = steps[steps.length - 1];
  if (last?.type === "text") return [...steps.slice(0, -1), { type: "text", text: last.text + text }];
  return [...steps, { type: "text", text }];
}

function StepView({ step }: { step: Step }) {
  switch (step.type) {
    case "mcp_connected":
      return <div className="event">🔌 Connected to MCP server · discovered {step.tools.length} tools</div>;
    case "tool_call":
      return (
        <details className="event tool">
          <summary>🛠 tools/call <code>{step.name}</code></summary>
          <pre>{JSON.stringify(step.input, null, 2)}</pre>
        </details>
      );
    case "tool_result":
      return (
        <details className={`event tool ${step.is_error ? "is-error" : ""}`}>
          <summary>{step.is_error ? "⚠️" : "✅"} result from <code>{step.name}</code></summary>
          <pre>{typeof step.output === "string" ? step.output : JSON.stringify(step.output, null, 2)}</pre>
        </details>
      );
    case "text":
      return <div className="bubble assistant"><Markdown>{step.text}</Markdown></div>;
    case "error":
      return <div className="bubble error">{step.message}</div>;
  }
}
