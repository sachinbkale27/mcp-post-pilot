import { useEffect, useRef, useState } from "react";
import { Dna, FilePlus2, ImagePlus, ListChecks, Menu, Microscope, Sparkles, WandSparkles } from "lucide-react";
import { BLOG_URL, getAgents, resetChat, streamChat, uploadImage, type AgentEvent, type AgentsInfo } from "./api";
import { Composer, MAX_ATTACHMENTS, type Attachment } from "./components/Composer";
import { prepareImage } from "./lib/images";
import { AgentTurn, UserMessage, type AgentStep, type Step, type Turn } from "./components/Messages";
import { Brand, Sidebar } from "./components/Sidebar";

const SUGGESTIONS = [
  { icon: ListChecks, title: "Catch me up", prompt: "What posts are on the blog, and what is each one about?" },
  { icon: Microscope, title: "Check a variant", prompt: "Is BRCA1 c.68_69del pathogenic, how common is it, and what is the strongest evidence?" },
  {
    icon: Dna, title: "Research, then write",
    prompt: "Research the CFTR F508del variant (ClinVar classification, what CFTR does, one recent paper on CFTR modulators), then write a short draft blog post about it with the sources, by sachin.",
  },
  { icon: FilePlus2, title: "Draft a post", prompt: "Write a short draft post explaining how MCP tools work, by sachin." },
];

const IMAGE_ONLY_PROMPT = "Here are some images.";

const IMAGE_CAPABILITIES = [
  {
    icon: ImagePlus,
    title: "Post with your photos",
    body: "Attach, paste or drop up to 4 images. I look at them, write around what they show, and place them as the cover or inline with descriptive alt text.",
    example: "Write a short post about the attached photo, use it as the cover, and keep it as a draft.",
  },
  {
    icon: WandSparkles,
    title: "Generate an illustration",
    body: "No image? Ask for one. I call the generate_image MCP tool, which creates an illustration with an AI image model and stores it on the blog for the post.",
    example: "Write a short post about autumn in the mountains, with a generated landscape cover image.",
  },
];

/** Apply a change to the delegation (agent step) with this id. */
function updateAgent(steps: Step[], id: string, fn: (s: AgentStep) => AgentStep): Step[] {
  return steps.map((s) => (s.type === "agent" && s.id === id ? fn(s) : s));
}

/** Apply one streamed event to the steps of the current turn. */
function applyEvent(steps: Step[], event: AgentEvent): Step[] {
  const last = steps[steps.length - 1];
  switch (event.type) {
    case "token":
      return last?.type === "text"
        ? [...steps.slice(0, -1), { type: "text", text: last.text + event.text }]
        : [...steps, { type: "text", text: event.text }];
    case "agent_start":
      return [
        ...steps,
        { type: "agent", id: event.id, agent: event.agent, title: event.title, task: event.task, tools: [], startedAt: performance.now() },
      ];
    case "agent_end":
      return updateAgent(steps, event.id, (s) => ({ ...s, isError: event.is_error, finishedAt: performance.now() }));
    case "tool_call":
      return updateAgent(steps, event.delegation, (s) => ({
        ...s,
        tools: [...s.tools, { type: "tool", id: event.id, name: event.name, input: event.input, startedAt: performance.now() }],
      }));
    case "tool_result":
      return updateAgent(steps, event.delegation, (s) => ({
        ...s,
        tools: s.tools.map((t) =>
          t.id === event.id ? { ...t, output: event.output, isError: event.is_error, finishedAt: performance.now() } : t,
        ),
      }));
    case "error":
      return [...steps, { type: "error", message: event.message }];
    default:
      return steps;
  }
}

export function App() {
  const [info, setInfo] = useState<AgentsInfo>();
  const [infoError, setInfoError] = useState<string>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const busy = turns.some((t) => t.pending);

  const loadInfo = () => {
    setInfoError(undefined);
    getAgents().then(setInfo).catch((e) => setInfoError(e.message));
  };
  useEffect(loadInfo, []);

  useEffect(() => {
    const first = turns[0] && (turns[0].user || "Images");
    document.title = first ? `${first.slice(0, 40)} · Post Pilot Agent` : "Post Pilot Agent";
  }, [turns]);

  // Follow new output only while the reader is at the bottom.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const updateLast = (fn: (t: Turn) => Turn) => setTurns((ts) => [...ts.slice(0, -1), fn(ts[ts.length - 1])]);
  const patchAttachment = (id: string, patch: Partial<Attachment>) =>
    setAttachments((list) => list.map((a) => (a.id === id ? { ...a, ...patch } : a)));

  /** Resize each file in the browser, then upload it to the blog's media store. */
  function addFiles(files: File[]) {
    const room = MAX_ATTACHMENTS - attachments.length;
    for (const file of files.slice(0, Math.max(0, room))) {
      const id = crypto.randomUUID();
      setAttachments((list) => [...list, { id, name: file.name, status: "processing" }]);
      prepareImage(file)
        .then(async ({ blob, dataUrl }) => {
          patchAttachment(id, { preview: dataUrl, status: "uploading" });
          patchAttachment(id, { url: await uploadImage(blob), status: "ready" });
        })
        .catch((e) => patchAttachment(id, { status: "error", error: (e as Error).message }));
    }
  }

  async function send(text: string) {
    const ready = attachments.filter((a) => a.status === "ready" && a.url && a.preview);
    if ((!text.trim() && ready.length === 0) || busy) return;
    const message = text.trim() || IMAGE_ONLY_PROMPT;
    const images = ready.map((a) => ({ url: a.url!, data_url: a.preview!, name: a.name }));
    setInput("");
    setAttachments([]);
    stickToBottom.current = true;
    setTurns((ts) => [
      ...ts,
      { user: text.trim(), images: images.map((i) => ({ url: i.url, preview: i.data_url, name: i.name })), steps: [], pending: true },
    ]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      for await (const event of streamChat(message, conversationId, images, controller.signal)) {
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
    setAttachments([]);
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
        onRetry={loadInfo}
        onClose={() => setSidebarOpen(false)}
      />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <main className="main">
        <header className="topbar">
          <button className="icon-btn only-mobile" onClick={() => setSidebarOpen(true)} aria-label="Open panel">
            <Menu size={19} />
          </button>
          <div className="only-mobile"><Brand /></div>
          <h1 className="topbar-title hide-mobile">{turns[0] ? turns[0].user || "Images" : "New conversation"}</h1>
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
              <h2>What should we work on today?</h2>
              <p>
                I coordinate a team of specialist agents, each with its own MCP server: the Blog agent
                works on <a href={BLOG_URL} target="_blank" rel="noreferrer">Post Pilot</a> (find, draft, edit,
                publish posts), the Genetics agent researches ClinVar, gnomAD, NCBI Gene and PubMed
                {info?.agents.some((a) => a.name === "labels") ? (
                  <>
                    , and the Labeling agent annotates your images in{" "}
                    <a href="https://labels.sachin-kale.com" target="_blank" rel="noreferrer">Image Label</a> and exports
                    COCO or YOLO training data
                  </>
                ) : null}
                .
                I hand each part of your request to the right agent, combine their results, and you see
                every delegation and tool call as it happens.
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

              <section className="capabilities" aria-labelledby="images-heading">
                <h3 id="images-heading"><ImagePlus size={16} aria-hidden /> Posts with images</h3>
                <div className="capability-grid">
                  {IMAGE_CAPABILITIES.map(({ icon: Icon, title, body, example }) => (
                    <div key={title} className="capability">
                      <span className="capability-icon"><Icon size={18} aria-hidden /></span>
                      <div>
                        <strong>{title}</strong>
                        <p>{body}</p>
                        <button className="capability-try" onClick={() => setInput(example)} disabled={busy}>
                          Try it →
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </section>
          ) : (
            <div className="thread">
              {turns.map((turn, i) => (
                <div key={i} className="turn">
                  <UserMessage text={turn.user} images={turn.images} />
                  <AgentTurn turn={turn} />
                </div>
              ))}
            </div>
          )}
        </div>

        <Composer
          value={input}
          busy={busy}
          attachments={attachments}
          onAddFiles={addFiles}
          onRemoveAttachment={(id) => setAttachments((list) => list.filter((a) => a.id !== id))}
          onChange={setInput}
          onSend={() => send(input)}
          onStop={() => abortRef.current?.abort()}
        />
      </main>
    </div>
  );
}
