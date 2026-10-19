import { useEffect, useRef, useState } from "react";
import { FilePlus2, ListChecks, Menu, ScanSearch, Sparkles, SquarePen } from "lucide-react";
import { BLOG_URL, getMcpInfo, resetChat, streamChat, type AgentEvent, type McpInfo } from "./api";
import { Composer } from "./components/Composer";
import { AgentTurn, UserMessage, type Step, type Turn } from "./components/Messages";
import { Brand, Sidebar } from "./components/Sidebar";

const SUGGESTIONS = [
  { icon: ListChecks, title: "Catch me up", prompt: "What posts are on the blog, and what is each one about?" },
  { icon: FilePlus2, title: "Draft a post", prompt: "Write a short draft post explaining how MCP tools work, by sachin." },
  { icon: ScanSearch, title: "Review a post", prompt: "Review the post “What is MCP?” for clarity and structure, and suggest concrete edits." },
  { icon: SquarePen, title: "Publishing queue", prompt: "Which posts are still drafts? Summarize what each needs before publishing." },
];

/** Apply one streamed agent event to the steps of the current turn. */
function applyEvent(steps: Step[], event: AgentEvent): Step[] {
  const last = steps[steps.length - 1];
  switch (event.type) {
    case "mcp_connected":
      return [...steps, { type: "connected", tools: event.tools.length }];
    case "token":
      return last?.type === "text"
        ? [...steps.slice(0, -1), { type: "text", text: last.text + event.text }]
        : [...steps, { type: "text", text: event.text }];
    case "tool_call":
      return [...steps, { type: "tool", id: event.id, name: event.name, input: event.input, startedAt: performance.now() }];
    case "tool_result":
      return steps.map((s) =>
        s.type === "tool" && s.id === event.id
          ? { ...s, output: event.output, isError: event.is_error, finishedAt: performance.now() }
          : s,
      );
    case "error":
      return [...steps, { type: "error", message: event.message }];
    default:
      return steps;
  }
}

export function App() {
  const [info, setInfo] = useState<McpInfo>();
  const [infoError, setInfoError] = useState<string>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string>();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const busy = turns.some((t) => t.pending);

  useEffect(() => {
    getMcpInfo().then(setInfo).catch((e) => setInfoError(e.message));
  }, []);

  useEffect(() => {
    document.title = turns[0] ? `${turns[0].user.slice(0, 40)} · Post Pilot Agent` : "Post Pilot Agent";
  }, [turns]);

  // Follow new output only while the reader is at the bottom.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const updateLast = (fn: (t: Turn) => Turn) => setTurns((ts) => [...ts.slice(0, -1), fn(ts[ts.length - 1])]);

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput("");
    stickToBottom.current = true;
    setTurns((ts) => [...ts, { user: text.trim(), steps: [], pending: true }]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      for await (const event of streamChat(text.trim(), conversationId, controller.signal)) {
        if (event.type === "conversation") setConversationId(event.id);
        else updateLast((t) => ({ ...t, steps: applyEvent(t.steps, event) }));
      }
    } catch (e) {
      const stopped = (e as Error).name === "AbortError";
      updateLast((t) => ({ ...t, steps: [...t.steps, stopped ? { type: "stopped" } : { type: "error", message: (e as Error).message }] }));
    } finally {
      abortRef.current = null;
      updateLast((t) => ({ ...t, pending: false }));
    }
  }

  async function newChat() {
    if (conversationId) await resetChat(conversationId).catch(() => {});
    setConversationId(undefined);
    setTurns([]);
    setSidebarOpen(false);
  }

  return (
    <div className="shell">
      <Sidebar
        info={info}
        infoError={infoError}
        busy={busy}
        open={sidebarOpen}
        onNewChat={newChat}
        onClose={() => setSidebarOpen(false)}
      />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <main className="main">
        <header className="topbar">
          <button className="icon-btn only-mobile" onClick={() => setSidebarOpen(true)} aria-label="Open panel">
            <Menu size={19} />
          </button>
          <div className="only-mobile"><Brand /></div>
          <h1 className="topbar-title hide-mobile">{turns[0]?.user ?? "New conversation"}</h1>
          {info && <span className="model-chip"><Sparkles size={13} aria-hidden /> {info.model}</span>}
        </header>

        <div
          className="scroll"
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
        >
          {turns.length === 0 ? (
            <section className="welcome">
              <div className="welcome-mark" aria-hidden>
                <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={56} height={56} />
              </div>
              <h2>What should we publish today?</h2>
              <p>
                I work on the blog{" "}
                <a href={BLOG_URL} target="_blank" rel="noreferrer">Post Pilot</a>{" "}
                through {info ? info.tools.length : "its"} MCP tools: I can find and read posts,
                draft new ones, edit, publish or delete them. You'll see every tool call as it happens.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map(({ icon: Icon, title, prompt }) => (
                  <button key={title} className="suggestion" onClick={() => send(prompt)} disabled={busy}>
                    <Icon size={18} aria-hidden />
                    <strong>{title}</strong>
                    <span>{prompt}</span>
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <div className="thread">
              {turns.map((turn, i) => (
                <div key={i} className="turn">
                  <UserMessage text={turn.user} />
                  <AgentTurn turn={turn} />
                </div>
              ))}
            </div>
          )}
        </div>

        <Composer
          value={input}
          busy={busy}
          onChange={setInput}
          onSend={() => send(input)}
          onStop={() => abortRef.current?.abort()}
        />
      </main>
    </div>
  );
}
