import { useEffect, useRef, useState, type DragEvent } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CircleAlert, Download, Eye, EyeOff, ImagePlus, Link2, LoaderCircle, RotateCcw, ScanSearch, Square, Stethoscope, Tag } from "lucide-react";
import { fetchImageFromUrl, streamDiagnosis, streamLabel, uploadImage, warmUpLabeling, type Annotation, type LabelResult } from "../api";
import { applyEvent } from "../lib/events";
import { ACCEPTED_TYPES, prepareImage, withGrid } from "../lib/images";
import { AgentCard, type Step } from "./Messages";

const EXAMPLES = [
  { instructions: "Outline every person and every car.", labels: "person, car" },
  { instructions: "Circle each coin and outline the banknotes.", labels: "coin, banknote" },
  { instructions: "Outline the main object in the photo.", labels: "" },
];

// Distinct colours on both the dark and light themes
const PALETTE = ["#2dd4bf", "#f59e0b", "#a78bfa", "#f43f5e", "#38bdf8", "#84cc16", "#ec4899", "#fb923c"];

interface Upload {
  name: string;
  preview?: string; // resized data URL: what is uploaded, shown and sent to the model
  url?: string;     // public /media/... URL once uploaded
  status: "processing" | "uploading" | "ready" | "error";
  error?: string;
}

interface Run {
  steps: Step[];
  result?: LabelResult;
  error?: string;
  pending: boolean;
}

interface Diagnosis {
  text: string;
  pending: boolean;
  error?: string;
}

interface Props {
  active: boolean;      // the view is showing
  available: boolean;   // the Labeling agent is configured and online
  unavailableReason?: string;
  busy: boolean;
  onBusyChange: (busy: boolean) => void;
}

/** Upload an image, say what to label, and watch the Labeling agent annotate it. */
export function LabelView({ active, available, unavailableReason, busy, onBusyChange }: Props) {
  const [upload, setUpload] = useState<Upload>();
  const [instructions, setInstructions] = useState("");
  const [labels, setLabels] = useState("");
  const [model, setModel] = useState<"sam" | "medsam">("sam");
  const [imageUrl, setImageUrl] = useState("");
  const [diagnosis, setDiagnosis] = useState<Diagnosis>();
  const diagnoseAbort = useRef<AbortController | null>(null);
  const [run, setRun] = useState<Run>();
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // The segmentation model takes a minute or two to start after a quiet spell: start it while the
  // user picks an image and writes instructions (again every few minutes while the view is open)
  useEffect(() => {
    if (!active || !available) return;
    warmUpLabeling(model);
    const timer = setInterval(() => warmUpLabeling(model), 4 * 60 * 1000);
    return () => clearInterval(timer);
  }, [active, available, model]);

  const canRun = available && !busy && upload?.status === "ready" && instructions.trim().length >= 3;

  function addFile(file: File | undefined) {
    if (!file || busy) return;
    setRun(undefined);
    diagnoseAbort.current?.abort();
    setDiagnosis(undefined);
    setUpload({ name: file.name, status: "processing" });
    prepareImage(file)
      .then(async ({ blob, dataUrl }) => {
        setUpload({ name: file.name, preview: dataUrl, status: "uploading" });
        const url = await uploadImage(blob);
        setUpload({ name: file.name, preview: dataUrl, url, status: "ready" });
      })
      .catch((e) => setUpload({ name: file.name, status: "error", error: (e as Error).message }));
  }

  /** Load an image from a web address, then handle it like a picked file. */
  function addUrl(raw: string) {
    const url = raw.trim();
    if (!url || busy) return;
    setRun(undefined);
    setUpload({ name: url, status: "processing" });
    fetchImageFromUrl(url)
      .then((file) => { setImageUrl(""); addFile(file); })
      .catch((e) => setUpload({ name: url, status: "error", error: (e as Error).message }));
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = Array.from(e.dataTransfer.files).find((f) => f.type.startsWith("image/"));
    // An image dragged from another web page arrives as its address, not as a file
    const url = e.dataTransfer.getData("text/uri-list").split(/\r?\n/).find((l) => l && !l.startsWith("#"));
    if (file) addFile(file);
    else if (url) addUrl(url);
  }

  async function start() {
    if (!canRun || !upload?.url || !upload.preview) return;
    const controller = new AbortController();
    abortRef.current = controller;
    onBusyChange(true);
    setRun({ steps: [], pending: true });
    const update = (fn: (r: Run) => Run) => setRun((r) => (r ? fn(r) : r));
    try {
      // The model sees a copy with a pixel grid; the saved image stays clean
      const grid = await withGrid(upload.preview);
      const request = {
        image: { url: upload.url, data_url: grid.dataUrl, name: upload.name },
        grid_step: grid.step,
        model,
        instructions: instructions.trim(),
        labels: labels.split(",").map((l) => l.trim()).filter(Boolean),
      };
      for await (const event of streamLabel(request, controller.signal)) {
        if (event.type === "label_result") update((r) => ({ ...r, result: event }));
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

  function reset() {
    diagnoseAbort.current?.abort();
    setUpload(undefined);
    setRun(undefined);
    setDiagnosis(undefined);
  }

  /** Stream an AI interpretation of the image; "What to label" is passed along as context. */
  async function diagnose() {
    if (!upload?.url || !upload.preview || diagnosis?.pending) return;
    const controller = new AbortController();
    diagnoseAbort.current = controller;
    setDiagnosis({ text: "", pending: true });
    try {
      const request = { image: { url: upload.url, data_url: upload.preview, name: upload.name }, context: instructions };
      for await (const event of streamDiagnosis(request, controller.signal)) {
        if (event.type === "token") setDiagnosis((d) => d && { ...d, text: d.text + event.text });
        else if (event.type === "error") setDiagnosis((d) => d && { ...d, error: event.message });
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setDiagnosis((d) => d && { ...d, error: (e as Error).message });
    } finally {
      setDiagnosis((d) => d && { ...d, pending: false });
      diagnoseAbort.current = null;
    }
  }

  return (
    <div className="label-view">
      <header className="label-intro">
        <h2><ScanSearch size={22} aria-hidden /> Annotate Images</h2>
        <p>
          Upload an image and say what to label. The Labeling agent saves it in Image Label and finds each
          object; Segment Anything (or MedSAM for medical scans) traces its exact outline. Download the
          result as COCO or YOLO training data.
        </p>
      </header>

      {!available && (
        <p className="label-alert">
          <CircleAlert size={16} aria-hidden /> {unavailableReason ?? "The Labeling agent isn't available on this server."}
        </p>
      )}

      <div className="label-grid">
        <section className="label-panel" aria-labelledby="label-image-heading">
          <h3 id="label-image-heading">1. Image</h3>
          {upload?.preview ? (
            <div className="label-picked">
              <img src={upload.preview} alt={upload.name} />
              <div className="label-picked-meta">
                <span className="mono" title={upload.name}>{upload.name}</span>
                <span className={`label-status status-${upload.status}`}>
                  {upload.status === "uploading" ? <><LoaderCircle size={13} className="spin" aria-hidden /> Uploading</> : "Uploaded"}
                </span>
                <button className="link-btn" onClick={() => fileRef.current?.click()} disabled={busy}>Change</button>
              </div>
            </div>
          ) : (
            <button
              className={dragging ? "label-drop dragging" : "label-drop"}
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              disabled={busy}
            >
              {upload?.status === "processing" ? <LoaderCircle size={22} className="spin" aria-hidden /> : <ImagePlus size={22} aria-hidden />}
              <strong>{upload?.status === "processing" ? "Preparing…" : "Choose or drop an image"}</strong>
              <span>JPEG, PNG, WebP, GIF or AVIF, or drag one from another web page. Large photos are resized to 1600 px.</span>
            </button>
          )}
          <form className="label-url" onSubmit={(e) => { e.preventDefault(); addUrl(imageUrl); }}>
            <Link2 size={15} aria-hidden />
            <input
              type="url"
              inputMode="url"
              value={imageUrl}
              placeholder="…or paste an image address (https://…)"
              aria-label="Image address"
              onChange={(e) => setImageUrl(e.target.value)}
              disabled={busy || upload?.status === "processing" || upload?.status === "uploading"}
            />
            <button type="submit" className="link-btn" disabled={busy || !imageUrl.trim() || upload?.status === "processing"}>
              Load
            </button>
          </form>
          {upload?.status === "error" && <p className="panel-error">{upload.error}</p>}
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPTED_TYPES.join(",")}
            hidden
            onChange={(e) => { addFile(e.target.files?.[0]); e.target.value = ""; }}
          />

          <h3>2. What to label</h3>
          <textarea
            className="label-input"
            rows={3}
            value={instructions}
            placeholder="e.g. Outline every person and every car."
            onChange={(e) => setInstructions(e.target.value)}
            disabled={busy}
          />
          <label className="label-field">
            <span><Tag size={13} aria-hidden /> Label names <em>(optional, comma-separated)</em></span>
            <input className="label-input" value={labels} placeholder="person, car" onChange={(e) => setLabels(e.target.value)} disabled={busy} />
          </label>
          <div className="label-field">
            <span id="label-model">Image type</span>
            <div className="segmented" role="radiogroup" aria-labelledby="label-model">
              {([["sam", "Photo or general image", "SAM"], ["medsam", "Medical scan", "MedSAM"]] as const).map(([value, text, name]) => (
                <button
                  key={value}
                  role="radio"
                  aria-checked={model === value}
                  className={model === value ? "active" : undefined}
                  onClick={() => setModel(value)}
                  disabled={busy}
                >
                  {text} <span className="mono">{name}</span>
                </button>
              ))}
            </div>
            {model === "medsam" && (
              <small className="label-hint">CT, MRI, X-ray, ultrasound, endoscopy or pathology. For research and datasets, not diagnosis.</small>
            )}
          </div>
          <div className="label-examples">
            {EXAMPLES.map((ex) => (
              <button key={ex.instructions} className="chip" onClick={() => { setInstructions(ex.instructions); setLabels(ex.labels); }} disabled={busy}>
                {ex.instructions}
              </button>
            ))}
          </div>

          <div className="label-actions">
            {busy ? (
              <button className="label-run" onClick={() => abortRef.current?.abort()}>
                <Square size={14} aria-hidden /> Stop
              </button>
            ) : (
              <button className="label-run" onClick={start} disabled={!canRun}>
                <ScanSearch size={16} aria-hidden /> Annotate Image
              </button>
            )}
            {diagnosis?.pending ? (
              <button className="label-secondary" onClick={() => diagnoseAbort.current?.abort()}>
                <Square size={14} aria-hidden /> Stop
              </button>
            ) : (
              <button className="label-secondary" onClick={diagnose} disabled={upload?.status !== "ready"} title="AI interpretation of the image (research and education, not a medical diagnosis)">
                <Stethoscope size={16} aria-hidden /> Diagnose
              </button>
            )}
            {(run || diagnosis) && !busy && !diagnosis?.pending && (
              <button className="link-btn" onClick={reset}><RotateCcw size={13} aria-hidden /> Start over</button>
            )}
          </div>
        </section>

        <section className="label-panel label-output" aria-live="polite" aria-labelledby="label-result-heading">
          <h3 id="label-result-heading">3. Result</h3>
          {diagnosis && (
            <section className="diagnosis" aria-labelledby="diagnosis-heading">
              <h4 id="diagnosis-heading">
                <Stethoscope size={15} aria-hidden /> AI interpretation
                {diagnosis.pending && <LoaderCircle size={14} className="spin" aria-label="Writing" />}
              </h4>
              <p className="diagnosis-notice">
                For research and education only: not a medical diagnosis. A single image, without the patient's
                history, is never enough to diagnose; a qualified clinician must review it.
              </p>
              {diagnosis.text ? (
                <div className="answer"><Markdown remarkPlugins={[remarkGfm]}>{diagnosis.text}</Markdown></div>
              ) : (
                diagnosis.pending && <p className="label-empty">Looking at the image…</p>
              )}
              {diagnosis.error && <p className="label-alert"><CircleAlert size={16} aria-hidden /> {diagnosis.error}</p>}
            </section>
          )}
          {!run && !diagnosis && <p className="label-empty">The annotated image appears here. Labeling usually takes 10 to 30 seconds.</p>}
          {run?.steps.map((step) => (step.type === "agent" ? <AgentCard key={step.id} step={step} /> : null))}
          {run?.pending && !run.steps.length && (
            <p className="label-empty"><LoaderCircle size={14} className="spin" aria-hidden /> Starting…</p>
          )}
          {run?.error && <p className="label-alert"><CircleAlert size={16} aria-hidden /> {run.error}</p>}
          {run?.result && upload?.preview && <LabelResultView result={run.result} image={upload.preview} name={upload.name} />}
        </section>
      </div>
    </div>
  );
}

function LabelResultView({ result, image, name }: { result: LabelResult; image: string; name: string }) {
  const labelNames = [...new Set(result.annotations.map((a) => a.label))];
  const colorOf = (label: string) => PALETTE[labelNames.indexOf(label) % PALETTE.length];
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [showText, setShowText] = useState(true);
  const visible = result.annotations.filter((a) => !hidden.has(a.label));
  const toggle = (label: string) =>
    setHidden((h) => { const next = new Set(h); next.has(label) ? next.delete(label) : next.add(label); return next; });
  const exportable = result.annotations.filter((a) => a.type === "polygon" || a.type === "circle").length;
  const base = name.replace(/\.[^.]+$/, "") || "image";

  return (
    <div className="label-result">
      <div className="label-canvas">
        <img src={image} alt={`${name} with ${result.annotations.length} annotations`} />
        <svg viewBox={`0 0 ${result.width} ${result.height}`} preserveAspectRatio="none" aria-hidden>
          {visible.map((a) => (
            <Shape key={a.id} annotation={a} color={colorOf(a.label)} size={Math.max(result.width, result.height)} showText={showText} />
          ))}
        </svg>
      </div>

      <div className="label-legend">
        {labelNames.map((label) => {
          const count = result.annotations.filter((a) => a.label === label).length;
          return (
            <button key={label} className={hidden.has(label) ? "legend-item off" : "legend-item"} onClick={() => toggle(label)} aria-pressed={!hidden.has(label)}>
              <span className="legend-swatch" style={{ background: colorOf(label) }} /> {label} <span className="count">{count}</span>
            </button>
          );
        })}
        <button className="link-btn legend-text" onClick={() => setShowText(!showText)}>
          {showText ? <EyeOff size={13} aria-hidden /> : <Eye size={13} aria-hidden />} {showText ? "Hide" : "Show"} names
        </button>
      </div>

      {result.annotations.length === 0 ? (
        <p className="label-alert"><CircleAlert size={16} aria-hidden /> The agent saved no annotations. Try more specific instructions.</p>
      ) : (
        <p className="label-note">
          Outlines are traced by Segment Anything from the agent's boxes; dashed ones scored low. Check that each
          outline is the right object before you train on it. {exportable < result.annotations.length && `${result.annotations.length - exportable} pin, arrow or rectangle shapes are left out of exports.`}
        </p>
      )}

      <div className="label-downloads">
        <button className="label-download" onClick={() => download(`${base}.coco.json`, JSON.stringify(result.exports.coco, null, 2), "application/json")} disabled={!exportable}>
          <Download size={14} aria-hidden /> COCO JSON
        </button>
        <button className="label-download" onClick={() => download(`${base}.txt`, result.exports.yolo.annotations + "\n", "text/plain")} disabled={!exportable}>
          <Download size={14} aria-hidden /> YOLO labels
        </button>
        <button className="label-download" onClick={() => download("classes.txt", result.exports.yolo.classes.join("\n") + "\n", "text/plain")} disabled={!exportable}>
          <Download size={14} aria-hidden /> YOLO classes
        </button>
      </div>

      <details className="label-report">
        <summary>Agent's report</summary>
        <div className="answer"><Markdown remarkPlugins={[remarkGfm]}>{result.report}</Markdown></div>
      </details>
      <p className="label-saved">
        Saved in <a href="https://labels.sachin-kale.com" target="_blank" rel="noreferrer">Image Label</a> as image{" "}
        <span className="mono">{result.image_id}</span> (in the shared agent account).
      </p>
    </div>
  );
}

function Shape({ annotation: a, color, size, showText }: { annotation: Annotation; color: string; size: number; showText: boolean }) {
  const stroke = Math.max(2, size / 300);
  const style = {
    stroke: color,
    strokeWidth: stroke,
    fill: a.type === "arrow" ? "none" : `${color}33`,
    strokeDasharray: a.confidence === "low" ? `${stroke * 3} ${stroke * 2}` : undefined,
  };
  const fontSize = Math.max(12, size / 40);
  let shape;
  let anchor = { x: a.x ?? 0, y: a.y ?? 0 };
  switch (a.type) {
    case "polygon":
      shape = <polygon points={(a.points ?? []).map((p) => `${p.x},${p.y}`).join(" ")} {...style} />;
      anchor = (a.points ?? []).reduce((top, p) => (p.y < top.y ? p : top), a.points?.[0] ?? anchor);
      break;
    case "circle":
      shape = <circle cx={a.x} cy={a.y} r={a.radius} {...style} />;
      anchor = { x: a.x ?? 0, y: (a.y ?? 0) - (a.radius ?? 0) };
      break;
    case "rectangle":
      shape = <rect x={a.x} y={a.y} width={a.width} height={a.height} {...style} />;
      break;
    case "pin":
      shape = <circle cx={a.x} cy={a.y} r={stroke * 3} {...style} fill={color} />;
      break;
    case "arrow":
      shape = <line x1={a.x} y1={a.y} x2={a.arrowTarget?.x} y2={a.arrowTarget?.y} {...style} />;
      break;
  }
  return (
    <g>
      <title>{`${a.label}${a.confidence ? ` (${a.confidence} confidence)` : ""}${a.notes ? `: ${a.notes}` : ""}`}</title>
      {shape}
      {showText && (
        <text x={anchor.x} y={Math.max(fontSize, anchor.y - stroke * 2)} fontSize={fontSize} fill={color} className="shape-label">
          {a.label}
        </text>
      )}
    </g>
  );
}

function download(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
