import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CircleAlert, CircleHelp, FlaskConical, LoaderCircle, RotateCcw, Search, Square, UserRound } from "lucide-react";
import { streamTrials } from "../api";
import { applyEvent } from "../lib/events";
import { filedTrials } from "../lib/tools";
import { AgentCard, type Step } from "./Messages";
import { TrialCards } from "./TrialCards";
import { type GuideStep, TrialsGuide } from "./TrialsGuide";

type Status = "recruiting" | "open" | "all";
type Sex = "" | "female" | "male";

/** The search form. Everything but the condition is optional. */
export interface TrialForm {
  condition: string;
  biomarker: string;
  drug: string;
  location: string;
  radius: string; // km, or "country" for anywhere in the named country or region
  phases: string[];
  status: Status;
  age: string;
  sex: Sex;
  details: string; // stage, prior treatments, other conditions
}

const EMPTY: TrialForm = {
  condition: "", biomarker: "", drug: "", location: "", radius: "300", phases: [], status: "open", age: "", sex: "", details: "",
};

const PHASES = ["Phase 1", "Phase 2", "Phase 3", "Phase 4"];
const RADII = [["50", "50 km"], ["100", "100 km"], ["300", "300 km"], ["1000", "1,000 km"], ["country", "Anywhere there"]] as const;
const STATUSES: [Status, string, string][] = [
  ["recruiting", "Recruiting now", "Enrolling participants today"],
  ["open", "Recruiting or opening soon", "Also trials approved but not enrolling yet"],
  ["all", "Any status", "Include completed and stopped trials, e.g. to see results"],
];

const EXAMPLES: { title: string; form: Partial<TrialForm> }[] = [
  { title: "Breast cancer near Pune", form: { condition: "breast cancer", biomarker: "HER2-low", location: "Pune, India", radius: "300" } },
  {
    title: "Lung cancer after osimertinib",
    form: {
      condition: "non-small cell lung cancer", biomarker: "EGFR", location: "India", radius: "country", phases: ["Phase 2", "Phase 3"],
      age: "60", sex: "female", details: "metastatic; progressed on osimertinib",
    },
  },
  { title: "Type 2 diabetes in Mumbai", form: { condition: "type 2 diabetes", location: "Mumbai, India", radius: "100", status: "recruiting" } },
];

/** The search in plain words: what the agent is asked, and what the user learns to write in chat. */
export function buildQuestion(f: TrialForm): string {
  const status = f.status === "recruiting" ? "recruiting " : f.status === "open" ? "recruiting or soon-recruiting " : "";
  const phases = f.phases.length ? `phase ${f.phases.map((p) => p.replace("Phase ", "")).join(" or ")} ` : "";
  let q = `Find ${status}${phases}clinical trials for ${f.condition.trim() || "…"}`;
  if (f.biomarker.trim()) q += ` (${f.biomarker.trim()})`;
  if (f.drug.trim()) q += ` testing ${f.drug.trim()}`;
  const place = f.location.trim();
  q += place ? (f.radius === "country" ? ` in ${place}` : ` within ${f.radius} km of ${place}`) : ", anywhere in the world";
  const who = f.sex === "female" ? "woman" : f.sex === "male" ? "man" : "person";
  if (f.age.trim()) q += `, for a ${f.age.trim()}-year-old ${who}`;
  else if (f.sex) q += `, for a ${who}`;
  if (f.details.trim()) q += `. About the patient: ${f.details.trim().replace(/\.$/, "")}`;
  if (f.status === "all") q += ". Include completed and stopped trials";
  return q + ".";
}

/** What is known about the person, for the agent's eligibility screen; empty when the search isn't for one. */
export function describePerson(f: TrialForm): string {
  if (!f.age.trim() && !f.sex && !f.details.trim()) return "";
  const who = [f.age.trim() && `${f.age.trim()}-year-old`, f.sex || "person"].filter(Boolean).join(" ");
  return [`${who} with ${f.condition.trim()}${f.biomarker.trim() ? ` (${f.biomarker.trim()})` : ""}`, f.details.trim()]
    .filter(Boolean)
    .join("; ");
}

interface Run {
  steps: Step[];
  report?: string;
  error?: string;
  pending: boolean;
}

interface Props {
  available: boolean;
  unavailableReason?: string;
  busy: boolean;
  onBusyChange: (busy: boolean) => void;
  prefill?: { condition: string; key: number }; // from Diagnose: "Find clinical trials"
}

/** Fill in a guided form, see the question it makes, and watch the Clinical Trials agent search the registry. */
export function TrialsView({ available, unavailableReason, busy, onBusyChange, prefill }: Props) {
  const [form, setForm] = useState<TrialForm>(EMPTY);
  const [guideStep, setGuideStep] = useState<GuideStep>("condition");
  const [showGuide, setShowGuide] = useState(false); // after a search; before one, the guide fills the results panel
  // The guide follows the form: focusing or clicking a part opens its help
  const guide = (step: GuideStep) => ({ onFocusCapture: () => setGuideStep(step), onClickCapture: () => setGuideStep(step) });
  const [run, setRun] = useState<Run>();
  const abortRef = useRef<AbortController | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const locationRef = useRef<HTMLInputElement>(null);
  const set = (patch: Partial<TrialForm>) => setForm((f) => ({ ...f, ...patch }));

  // Diagnose hands over its leading diagnosis: fill it in and ask for a place
  useEffect(() => {
    if (!prefill) return;
    setForm({ ...EMPTY, condition: prefill.condition });
    setRun(undefined);
    locationRef.current?.focus();
  }, [prefill]);

  const question = buildQuestion(form);
  const canRun = available && !busy && form.condition.trim().length >= 3;
  const agent = run?.steps.find((s) => s.type === "agent");
  const filed = agent?.type === "agent" ? filedTrials(agent.tools) : undefined;
  const summary = agent?.type === "agent"
    ? ([...agent.tools].reverse().find((t) => t.name === "submit_trials" && !t.isError)?.input.summary_text as string | undefined)
    : undefined;

  useEffect(() => {
    if (filed) resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [filed !== undefined]); // eslint-disable-line react-hooks/exhaustive-deps

  async function search() {
    if (!canRun) return;
    setShowGuide(false);
    setGuideStep("results");
    const controller = new AbortController();
    abortRef.current = controller;
    onBusyChange(true);
    setRun({ steps: [], pending: true });
    const update = (fn: (r: Run) => Run) => setRun((r) => (r ? fn(r) : r));
    try {
      for await (const event of streamTrials({ question, person: describePerson(form) }, controller.signal)) {
        if (event.type === "trials_report") update((r) => ({ ...r, report: event.report }));
        else if (event.type === "error") update((r) => ({ ...r, error: event.message }));
        else update((r) => ({ ...r, steps: applyEvent(r.steps, event) }));
      }
    } catch (e) {
      const stopped = (e as Error).name === "AbortError";
      update((r) => ({ ...r, error: stopped ? "Stopped." : (e as Error).message }));
    } finally {
      abortRef.current = null;
      update((r) => ({ ...r, pending: false }));
      onBusyChange(false);
    }
  }

  const togglePhase = (p: string) =>
    set({ phases: form.phases.includes(p) ? form.phases.filter((x) => x !== p) : [...form.phases, p].sort() });

  return (
    <div className="label-view">
      <header className="label-intro">
        <h2><FlaskConical size={22} aria-hidden /> Clinical Trials</h2>
        <p>
          Search the public <a href="https://clinicaltrials.gov" target="_blank" rel="noreferrer">ClinicalTrials.gov</a> registry.
          The Clinical Trials agent finds matching trials, reads their eligibility criteria, and explains why each one
          matched and what the trial team must confirm. For a specific patient, it also leaves out trials whose criteria
          rule them out.
        </p>
        {run && (
          <button className="link-btn" onClick={() => setShowGuide(!showGuide)} aria-expanded={showGuide}>
            <CircleHelp size={14} aria-hidden /> {showGuide ? "Hide the guide" : "How to use this page"}
          </button>
        )}
      </header>

      {!available && (
        <p className="label-alert">
          <CircleAlert size={16} aria-hidden /> {unavailableReason ?? "The Clinical Trials agent isn't available on this server."}
        </p>
      )}

      <div className="label-grid">
        <section className="label-panel" aria-labelledby="trials-form-heading">
          <h3 id="trials-form-heading">1. What are you looking for?</h3>
          <small className="label-hint">Only the disease is required; every detail you add narrows the search.</small>
          <label className="label-field" {...guide("condition")}>
            <span>Disease or condition</span>
            <input className="label-input" value={form.condition} placeholder="e.g. breast cancer, type 2 diabetes, asthma"
              onChange={(e) => set({ condition: e.target.value })} disabled={busy} />
          </label>
          <label className="label-field" {...guide("test")}>
            <span>Lab test result <em>(if known)</em></span>
            <input className="label-input" value={form.biomarker} placeholder="e.g. HER2-positive, EGFR, BRAF V600E"
              aria-describedby="trials-biomarker-help" onChange={(e) => set({ biomarker: e.target.value })} disabled={busy} />
            <small id="trials-biomarker-help" className="label-hint">
              Mostly for cancers, e.g. "HER2-positive" breast cancer: copy it from your pathology or genetic test
              report. Leave it blank if you're not sure.
            </small>
          </label>
          <label className="label-field" {...guide("treatment")}>
            <span>A treatment you're interested in <em>(optional)</em></span>
            <input className="label-input" value={form.drug} placeholder="e.g. immunotherapy, pembrolizumab"
              aria-describedby="trials-drug-help" onChange={(e) => set({ drug: e.target.value })} disabled={busy} />
            <small id="trials-drug-help" className="label-hint">Only trials testing this treatment. Leave blank to see all.</small>
          </label>

          <h3>2. Where?</h3>
          <div className="trials-row" {...guide("place")}>
            <label className="label-field">
              <span>City or country</span>
              <input ref={locationRef} className="label-input" value={form.location} placeholder="Blank: worldwide"
                onChange={(e) => set({ location: e.target.value })} disabled={busy} />
            </label>
            <label className="label-field">
              <span>Distance</span>
              <select className="label-input" value={form.radius} onChange={(e) => set({ radius: e.target.value })}
                disabled={busy || !form.location.trim()}>
                {RADII.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
              </select>
            </label>
          </div>

          <h3>3. Which trials?</h3>
          <div className="label-field" {...guide("status")}>
            <span id="trials-status">Status</span>
            <div className="trials-options" role="radiogroup" aria-labelledby="trials-status">
              {STATUSES.map(([value, text, help]) => (
                <button key={value} role="radio" aria-checked={form.status === value} title={help}
                  className={form.status === value ? "chip active" : "chip"} onClick={() => set({ status: value })} disabled={busy}>
                  {text}
                </button>
              ))}
            </div>
          </div>
          <div className="label-field" {...guide("phase")}>
            <span id="trials-phase">Phase <em>(none: any phase)</em></span>
            <div className="trials-options" role="group" aria-labelledby="trials-phase">
              {PHASES.map((p) => (
                <button key={p} aria-pressed={form.phases.includes(p)} className={form.phases.includes(p) ? "chip active" : "chip"}
                  onClick={() => togglePhase(p)} disabled={busy}>
                  {p}
                </button>
              ))}
            </div>
            <small className="label-hint">Phase 1 tests safety, phase 2 whether it works, phase 3 compares it with the standard treatment.</small>
          </div>

          <div {...guide("patient")}>
            <h3><UserRound size={13} aria-hidden /> 4. For a specific patient <em>(optional)</em></h3>
            <small className="label-hint">Fill these in to check each trial's rules against the patient. Leave them blank for a general search.</small>
            <div className="trials-patient">
              <div className="trials-row">
                <label className="label-field">
                  <span>Age</span>
                  <input className="label-input" inputMode="numeric" value={form.age} placeholder="e.g. 60"
                    onChange={(e) => set({ age: e.target.value.replace(/\D/g, "").slice(0, 3) })} disabled={busy} />
                </label>
                <label className="label-field">
                  <span>Sex</span>
                  <select className="label-input" value={form.sex} onChange={(e) => set({ sex: e.target.value as Sex })} disabled={busy}>
                    <option value="">Not specified</option>
                    <option value="female">Female</option>
                    <option value="male">Male</option>
                  </select>
                </label>
              </div>
              <label className="label-field">
                <span>Stage, prior treatments, other conditions</span>
                <textarea className="label-input" rows={2} value={form.details} placeholder="e.g. metastatic; progressed on osimertinib"
                  onChange={(e) => set({ details: e.target.value })} disabled={busy} />
              </label>
              <small className="label-hint">Don't enter names or other identifying details.</small>
            </div>
          </div>

          <div className="trials-question" aria-live="polite">
            <span>The agent will be asked</span>
            <p>{question}</p>
          </div>

          <div className="label-examples" {...guide("try")}>
            {EXAMPLES.map((ex) => (
              <button key={ex.title} className="chip" disabled={busy}
                onClick={() => setForm({ ...EMPTY, ...ex.form })}>
                {ex.title}
              </button>
            ))}
          </div>

          <div className="label-actions">
            {busy ? (
              <button className="label-run" onClick={() => abortRef.current?.abort()}>
                <Square size={14} aria-hidden /> Stop
              </button>
            ) : (
              <button className="label-run" onClick={search} disabled={!canRun}>
                <Search size={16} aria-hidden /> Find trials
              </button>
            )}
            {run && !busy && (
              <button className="link-btn" onClick={() => { setRun(undefined); setForm(EMPTY); }}>
                <RotateCcw size={13} aria-hidden /> Start over
              </button>
            )}
          </div>
        </section>

        <section className="label-panel label-output" aria-live="polite" aria-labelledby="trials-result-heading">
          <h3 id="trials-result-heading">{run ? "Results" : "Guide"}</h3>
          {(!run || showGuide) && <TrialsGuide active={guideStep} onSelect={setGuideStep} />}

          <div ref={resultRef} className="label-result-anchor">
            {summary && <p className="trials-summary">{summary}</p>}
            {filed && <TrialCards trials={filed.trials} notes={filed.notes} />}
            {!filed && run?.report && !run.pending && (
              <div className="answer"><Markdown remarkPlugins={[remarkGfm]}>{run.report}</Markdown></div>
            )}
          </div>
          {run?.pending && (
            <p className="label-progress">
              <LoaderCircle size={15} className="spin" aria-hidden />
              Searching the registry and reading eligibility criteria…
              <span>usually 20 to 60 seconds</span>
            </p>
          )}
          {run?.error && <p className="label-alert"><CircleAlert size={16} aria-hidden /> {run.error}</p>}
          {run?.steps.map((step) => (step.type === "agent" ? <AgentCard key={step.id} step={step} showTrials={false} /> : null))}
        </section>
      </div>
    </div>
  );
}
