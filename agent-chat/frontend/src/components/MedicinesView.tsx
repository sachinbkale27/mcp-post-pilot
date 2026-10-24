import { useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CircleAlert, LoaderCircle, Pill, RotateCcw, Search, Square } from "lucide-react";
import { streamDrugs } from "../api";
import { applyEvent } from "../lib/events";
import { AgentCard, type Step } from "./Messages";
import { MedicinesFaq } from "./MedicinesFaq";

type Topic = "uses" | "dosing" | "side_effects" | "warnings" | "do_not_use" | "interactions" | "pregnancy" | "reports" | "recalls";

/** Each topic: its chip, and how the question asks for it. */
const TOPICS: [Topic, string, string][] = [
  ["uses", "What it's for", "what it is used for"],
  ["dosing", "How it's taken", "how it is usually taken"],
  ["side_effects", "Side effects", "its side effects"],
  ["warnings", "Serious warnings", "its most serious warnings"],
  ["do_not_use", "Who shouldn't take it", "who should not take it"],
  ["interactions", "Other medicines", "what the label says about taking it with other medicines"],
  ["pregnancy", "Pregnancy and breastfeeding", "whether it can be used in pregnancy or while breastfeeding"],
  ["reports", "Reports to the FDA", "what people have reported to the FDA"],
  ["recalls", "Recalls", "any FDA recalls"],
];

export interface MedicineForm {
  name: string;
  topics: Topic[];
  others: string; // other medicines, food or alcohol
  own: string; // the user's own question
}

const EMPTY: MedicineForm = { name: "", topics: ["uses", "side_effects", "warnings"], others: "", own: "" };

const EXAMPLES: { title: string; form: Partial<MedicineForm> }[] = [
  { title: "Ozempic with insulin", form: { name: "Ozempic", topics: ["warnings", "interactions", "reports"], others: "insulin" } },
  { title: "Ibuprofen in pregnancy", form: { name: "ibuprofen", topics: ["pregnancy", "do_not_use"] } },
  { title: "Metformin recalls", form: { name: "metformin", topics: ["uses", "recalls"] } },
];

/** The question in plain words: what the agent is asked, and what the user learns to write in chat. */
export function buildQuestion(f: MedicineForm): string {
  const others = f.others.trim();
  const topics = TOPICS.filter(([t]) => f.topics.includes(t) && !(t === "interactions" && others)).map(([, , ask]) => ask);
  let q = `About ${f.name.trim() || "…"}`;
  q += topics.length ? `: ${topics.length > 1 ? `${topics.slice(0, -1).join(", ")} and ${topics.at(-1)}` : topics[0]}.` : ".";
  if (others) q += ` What does the label say about taking it with ${others}?`;
  if (f.own.trim()) q += ` ${f.own.trim().replace(/([^.?!])$/, "$1?")}`;
  return q;
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
}

/** Ask about a medicine with a short form, and watch the Drug Information agent read its FDA label. */
export function MedicinesView({ available, unavailableReason, busy, onBusyChange }: Props) {
  const [form, setForm] = useState<MedicineForm>(EMPTY);
  const [run, setRun] = useState<Run>();
  const abortRef = useRef<AbortController | null>(null);
  const set = (patch: Partial<MedicineForm>) => setForm((f) => ({ ...f, ...patch }));

  const question = buildQuestion(form);
  const canRun = available && !busy && form.name.trim().length >= 2;

  const toggle = (t: Topic) =>
    set({ topics: form.topics.includes(t) ? form.topics.filter((x) => x !== t) : TOPICS.map(([x]) => x).filter((x) => x === t || form.topics.includes(x)) });

  async function lookUp() {
    if (!canRun) return;
    const controller = new AbortController();
    abortRef.current = controller;
    onBusyChange(true);
    setRun({ steps: [], pending: true });
    const update = (fn: (r: Run) => Run) => setRun((r) => (r ? fn(r) : r));
    try {
      for await (const event of streamDrugs({ question }, controller.signal)) {
        if (event.type === "drug_report") update((r) => ({ ...r, report: event.report }));
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

  return (
    <div className="label-view">
      <header className="label-intro">
        <h2><Pill size={22} aria-hidden /> Medicines</h2>
        <p>
          Plain-language answers about a medicine from its official FDA label: what it's for, side effects, warnings,
          interactions and pregnancy, plus reports to the FDA and recalls. Every point quotes the label, with a link to
          the full label on DailyMed.
        </p>
        <MedicinesFaq />
      </header>

      {!available && (
        <p className="label-alert">
          <CircleAlert size={16} aria-hidden /> {unavailableReason ?? "The Drug Information agent isn't available on this server."}
        </p>
      )}

      <div className="label-grid">
        <section className="label-panel" aria-labelledby="medicine-form-heading">
          <h3 id="medicine-form-heading">1. Which medicine?</h3>
          <label className="label-field">
            <span>Medicine name</span>
            <input className="label-input" value={form.name} placeholder="e.g. Ozempic, metformin, ibuprofen"
              onChange={(e) => set({ name: e.target.value })} onKeyDown={(e) => e.key === "Enter" && lookUp()} disabled={busy} />
            <small className="label-hint">A brand or generic name; spelling mistakes are fine.</small>
          </label>

          <h3>2. What do you want to know? <em>(optional)</em></h3>
          <div className="trials-options" role="group" aria-label="Topics">
            {TOPICS.map(([t, text]) => (
              <button key={t} aria-pressed={form.topics.includes(t)} className={form.topics.includes(t) ? "chip active" : "chip"}
                onClick={() => toggle(t)} disabled={busy}>
                {text}
              </button>
            ))}
          </div>
          <label className="label-field">
            <span>Other medicines, food or alcohol <em>(optional)</em></span>
            <input className="label-input" value={form.others} placeholder="e.g. insulin, warfarin, alcohol"
              onChange={(e) => set({ others: e.target.value })} disabled={busy} />
            <small className="label-hint">Checks what the label says about taking them together.</small>
          </label>
          <label className="label-field">
            <span>Your question <em>(optional)</em></span>
            <textarea className="label-input" rows={2} value={form.own} placeholder="e.g. Should it be taken with food?"
              onChange={(e) => set({ own: e.target.value })} disabled={busy} />
            <small className="label-hint">Don't enter names or other identifying details.</small>
          </label>

          <div className="trials-question" aria-live="polite">
            <span>The agent will be asked</span>
            <p>{question}</p>
          </div>

          <div className="label-examples">
            {EXAMPLES.map((ex) => (
              <button key={ex.title} className="chip" disabled={busy} onClick={() => setForm({ ...EMPTY, ...ex.form })}>
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
              <button className="label-run" onClick={lookUp} disabled={!canRun}>
                <Search size={16} aria-hidden /> Look it up
              </button>
            )}
            {run && !busy && (
              <button className="link-btn" onClick={() => { setRun(undefined); setForm(EMPTY); }}>
                <RotateCcw size={13} aria-hidden /> Start over
              </button>
            )}
          </div>
        </section>

        <section className="label-panel label-output" aria-live="polite" aria-labelledby="medicine-result-heading">
          <h3 id="medicine-result-heading">Answer</h3>
          {!run && (
            <ol className="medicine-steps">
              <li><strong>Finds the medicine</strong> by brand or generic name, and its official FDA label.</li>
              <li><strong>Reads only the parts you asked about</strong>, plus FDA reports and recalls when chosen.</li>
              <li><strong>Answers in plain language</strong>, quoting the label for every point, with a link to the full label.</li>
            </ol>
          )}
          {run?.report && !run.pending && (
            <div className="answer"><Markdown remarkPlugins={[remarkGfm]}>{run.report}</Markdown></div>
          )}
          {run?.pending && (
            <p className="label-progress">
              <LoaderCircle size={15} className="spin" aria-hidden />
              Reading the FDA label…
              <span>usually 20 to 40 seconds</span>
            </p>
          )}
          {run?.error && <p className="label-alert"><CircleAlert size={16} aria-hidden /> {run.error}</p>}
          {run?.steps.map((step) => (step.type === "agent" ? <AgentCard key={step.id} step={step} showTrials={false} /> : null))}
        </section>
      </div>
    </div>
  );
}
