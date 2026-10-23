import { useEffect, useRef, useState } from "react";
import { Dna, FlaskConical, ImagePlus, ListChecks, MapPin, Menu, Microscope, SearchCheck, Sparkles, Target, WandSparkles } from "lucide-react";
import { BLOG_URL, getAgents, resetChat, streamChat, uploadImage, type AgentsInfo } from "./api";
import { Composer, MAX_ATTACHMENTS, type Attachment } from "./components/Composer";
import { prepareImage } from "./lib/images";
import { AgentTurn, UserMessage, type Turn } from "./components/Messages";
import { applyEvent } from "./lib/events";
import { LabelView } from "./components/LabelView";
import { TrialsView } from "./components/TrialsView";
import { Brand, Sidebar, type View } from "./components/Sidebar";

const SUGGESTIONS = [
  { icon: ListChecks, title: "Catch me up", prompt: "What posts are on the blog, and what is each one about?" },
  { icon: Microscope, title: "Check a variant", prompt: "Is BRCA1 c.68_69del pathogenic, how common is it, and what is the strongest evidence?" },
  {
    icon: Dna, title: "Research, then write",
    prompt: "Research the CFTR F508del variant (ClinVar classification, what CFTR does, one recent paper on CFTR modulators), then write a short draft blog post about it with the sources, by sachin.",
  },
  { icon: SearchCheck, title: "Fact-check a post", prompt: "Fact-check the latest published post and tell me what, if anything, needs fixing." },
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

/** Example questions for the Clinical Trials agent; each shows one kind of search. */
const TRIAL_EXAMPLES = [
  {
    icon: MapPin,
    title: "Trials near you",
    body: "Name the condition and a city: it searches recruiting trials within a radius and shows the nearest site.",
    example: "Find recruiting clinical trials for HER2-low breast cancer within 300 km of Pune.",
  },
  {
    icon: Target,
    title: "Match a patient profile",
    body: "Add age, sex, a biomarker or prior treatments: it reads each trial's criteria and lists what the trial team must confirm.",
    example: "Phase 2 or 3 trials for EGFR-mutant non-small cell lung cancer that progressed on osimertinib, for a 60-year-old woman, in India.",
  },
  {
    icon: FlaskConical,
    title: "What's being tested",
    body: "Ask about a condition or drug class: it summarises trials by intervention, phase and sponsor, or checks a claim about a trial.",
    example: "What treatments are being tested in clinical trials for diabetic foot ulcers, and in which phases?",
  },
];

const HASHES: Record<string, View> = { "#annotate": "label", "#label": "label", "#trials": "trials" };

/** #annotate (or the earlier #label) opens the annotation view, #trials the clinical trials search. */
function viewFromHash(): View {
  return HASHES[location.hash] ?? "chat";
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
  const [view, setView] = useState<View>(viewFromHash);
  const [labeling, setLabeling] = useState(false);
  const [focusComposer, setFocusComposer] = useState(0);
  const [searchingTrials, setSearchingTrials] = useState(false);
  const [trialsPrefill, setTrialsPrefill] = useState<{ condition: string; key: number }>();
  const trialsAgent = info?.agents.find((a) => a.name === "trials");
  const labelsAgent = info?.agents.find((a) => a.name === "labels");

  // #annotate opens the annotation view, so it can be linked to and survives a reload
  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  function openView(next: View) {
    setView(next);
    setSidebarOpen(false);
    const hash = next === "label" ? "#annotate" : next === "trials" ? "#trials" : "";
    history.replaceState(null, "", hash || location.pathname + location.search);
  }

  const loadInfo = () => {
    setInfoError(undefined);
    getAgents().then(setInfo).catch((e) => setInfoError(e.message));
  };
  useEffect(loadInfo, []);

  useEffect(() => {
    const first = turns[0] && (turns[0].user || "Images");
    const title = view === "label" ? "Annotate Images" : view === "trials" ? "Clinical Trials" : first && first.slice(0, 40);
    document.title = title ? `${title} · Post Pilot Agent` : "Post Pilot Agent";
  }, [turns, view]);

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

  /** Put a question in the chat box for the user to finish (e.g. add their city) and send. */
  function draft(text: string) {
    openView("chat");
    setInput(text);
    setFocusComposer((n) => n + 1);
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
        view={view}
        labelingAvailable={!!labelsAgent}
        trialsAvailable={!!trialsAgent}
        onViewChange={openView}
        onNewChat={() => { newChat(); openView("chat"); }}
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
          <h1 className="topbar-title hide-mobile">
            {view === "label" ? "Annotate Images" : view === "trials" ? "Clinical Trials" : turns[0] ? turns[0].user || "Images" : "New conversation"}
          </h1>
          {info && <span className="model-chip"><Sparkles size={13} aria-hidden /> {info.model}</span>}
        </header>

        {/* Both views stay mounted, so switching doesn't lose a conversation or a labeling run */}
        <div className="scroll" hidden={view !== "label"}>
          <LabelView
            active={view === "label"}
            available={!info || !!labelsAgent?.online}
            unavailableReason={
              !labelsAgent
                ? "The Image Annotation Agent isn't configured on this server."
                : `The Image Annotation Agent is offline${labelsAgent.error ? `: ${labelsAgent.error}` : "."}`
            }
            busy={labeling}
            onBusyChange={setLabeling}
            onFindTrials={
              trialsAgent
                ? (dx) => { setTrialsPrefill({ condition: dx, key: Date.now() }); openView("trials"); }
                : undefined
            }
          />
        </div>

        <div className="scroll" hidden={view !== "trials"}>
          <TrialsView
            available={!info || !!trialsAgent?.online}
            unavailableReason={
              !trialsAgent
                ? "The Clinical Trials agent isn't configured on this server."
                : `The Clinical Trials agent is offline${trialsAgent.error ? `: ${trialsAgent.error}` : "."}`
            }
            busy={searchingTrials}
            onBusyChange={setSearchingTrials}
            prefill={trialsPrefill}
          />
        </div>

        <div
          className="scroll"
          hidden={view !== "chat"}
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
                    , and the Image Annotation Agent annotates your images in{" "}
                    <a href="https://labels.sachin-kale.com" target="_blank" rel="noreferrer">Image Label</a> and exports
                    COCO or YOLO training data (try{" "}
                    <a href="#annotate" onClick={(e) => { e.preventDefault(); openView("label"); }}>Annotate Images</a>)
                  </>
                ) : null}
                {info?.agents.some((a) => a.name === "factcheck")
                  ? ", the Fact-check agent verifies claims and links against web sources"
                  : null}
                {info?.agents.some((a) => a.name === "trials")
                  ? ", and the Clinical Trials agent finds trials in the ClinicalTrials.gov registry"
                  : null}
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

              {info?.agents.some((a) => a.name === "trials") && (
                <section className="capabilities" aria-labelledby="trials-heading">
                  <h3 id="trials-heading"><FlaskConical size={16} aria-hidden /> Clinical trials</h3>
                  <p className="capabilities-intro">
                    Searches the public ClinicalTrials.gov registry. The more you say (condition, place, age,
                    biomarker, prior treatment), the better the matches. It explains each trial; only the trial
                    team can confirm eligibility. Prefer a form? Use the{" "}
                    <a href="#trials" onClick={(e) => { e.preventDefault(); openView("trials"); }}>Clinical Trials search</a>.
                  </p>
                  <div className="capability-grid">
                    {TRIAL_EXAMPLES.map(({ icon: Icon, title, body, example }) => (
                      <div key={title} className="capability">
                        <span className="capability-icon"><Icon size={18} aria-hidden /></span>
                        <div>
                          <strong>{title}</strong>
                          <p>{body}</p>
                          <p className="capability-example">“{example}”</p>
                          <button className="capability-try" onClick={() => draft(example)} disabled={busy}>
                            Try it →
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

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

        {view === "chat" && <Composer
          value={input}
          focusSignal={focusComposer}
          busy={busy}
          attachments={attachments}
          onAddFiles={addFiles}
          onRemoveAttachment={(id) => setAttachments((list) => list.filter((a) => a.id !== id))}
          onChange={setInput}
          onSend={() => send(input)}
          onStop={() => abortRef.current?.abort()}
        />}
      </main>
    </div>
  );
}
