import { useEffect, useRef, useState, type DragEvent } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CircleAlert, CircleCheck, Download, FlaskConical, PenTool, Sparkles, SquareArrowOutUpRight, Gauge, ImagePlus, Link2, LoaderCircle, Microscope, Palette, RotateCcw, ScanSearch, Square, Stethoscope, Tag, TriangleAlert, Undo2 } from "lucide-react";
import {
  fetchImageFromUrl, streamDiagnosis, streamLabel, streamPathology, uploadImage, warmUpLabeling,
  type AgentEvent, type DiagnosisRegion, type LabelResult, type PathologyAction, type QualityResult,
} from "../api";
import { applyEvent } from "../lib/events";
import { ACCEPTED_TYPES, prepareImage, withGrid } from "../lib/images";
import { AgentCard, type Step } from "./Messages";
import { AnnotatedImage, layerOf } from "./AnnotationLayers";

const EXAMPLES = [
  { instructions: "Outline every person and every car.", labels: "person, car" },
  { instructions: "Circle each coin and outline the banknotes.", labels: "coin, banknote" },
  { instructions: "Outline the main object in the photo.", labels: "" },
];

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
  quality?: QualityResult;
  error?: string;
  pending: boolean;
  action?: PathologyAction; // a histology tool run, not the agent
}

const PROGRESS: Record<PathologyAction, string> = {
  nuclei: "Finding nuclei with StarDist…",
  quality: "Checking image quality…",
  normalize: "Normalizing the stain colours…",
};

interface Diagnosis {
  text: string;
  pending: boolean;
  error?: string;
  regions?: DiagnosisRegion[];
  suspected?: string;
}

type Model = "sam" | "medsam";

interface Props {
  active: boolean;      // the view is showing
  available: boolean;   // the Image Annotation Agent is configured and online
  onFindTrials?: (diagnosis: string) => void; // when the Clinical Trials agent is configured
  unavailableReason?: string;
  busy: boolean;
  onBusyChange: (busy: boolean) => void;
}

/** Upload an image, say what to label, and watch the Image Annotation Agent annotate it. */
export function LabelView({ active, available, unavailableReason, busy, onBusyChange, onFindTrials }: Props) {
  const [upload, setUpload] = useState<Upload>();
  const [instructions, setInstructions] = useState("");
  const [labels, setLabels] = useState("");
  const [model, setModel] = useState<Model>("sam");
  const [imageUrl, setImageUrl] = useState("");
  const [diagnosis, setDiagnosis] = useState<Diagnosis>();
  const diagnoseAbort = useRef<AbortController | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const [run, setRun] = useState<Run>();
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // The image's id in Image Label once a run has uploaded it, so the histology tools don't upload it again
  const [labelImageId, setLabelImageId] = useState<string>();
  // While the stain-normalized copy is shown: the original, to go back to
  const [original, setOriginal] = useState<{ upload: Upload; imageId?: string }>();

  // The segmentation model takes a minute or two to start after a quiet spell: start it while the
  // user picks an image and writes instructions (again every few minutes while the view is open)
  useEffect(() => {
    if (!active || !available) return;
    warmUpLabeling(model);
    const timer = setInterval(() => warmUpLabeling(model), 4 * 60 * 1000);
    return () => clearInterval(timer);
  }, [active, available, model]);

  // Bring the annotated image into view when it arrives
  useEffect(() => {
    if (run?.result) resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [run?.result]);

  const canRun = available && !busy && upload?.status === "ready" && instructions.trim().length >= 3;

  function addFile(file: File | undefined, keepOriginal = false) {
    if (!file || (busy && !keepOriginal)) return;
    setRun(undefined);
    setLabelImageId(undefined);
    if (!keepOriginal) setOriginal(undefined);
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

  /** Run the Image Annotation Agent: with the form's settings, or with the areas a diagnosis found. */
  async function start(areas?: { instructions: string; labels: string[]; model: Model }) {
    if (!upload?.url || !upload.preview || busy || !available) return;
    if (!areas && !canRun) return;
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
        model: areas?.model ?? model,
        instructions: areas?.instructions ?? instructions.trim(),
        labels: areas?.labels ?? labels.split(",").map((l) => l.trim()).filter(Boolean),
        image_id: labelImageId, // add to the same Image Label image as earlier runs (e.g. its nuclei)
      };
      for await (const event of streamLabel(request, controller.signal)) {
        if (event.type === "label_result") {
          update((r) => ({ ...r, result: event }));
          setLabelImageId(event.image_id);
        }
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
    setLabelImageId(undefined);
    setOriginal(undefined);
  }

  /** Run one histology tool on the image: nuclei outlines, a quality check, or a stain-normalized copy. */
  async function runTool(action: PathologyAction) {
    if (!upload?.url || !upload.preview || busy || !available) return;
    const controller = new AbortController();
    abortRef.current = controller;
    onBusyChange(true);
    setRun({ steps: [], pending: true, action });
    const update = (fn: (r: Run) => Run) => setRun((r) => (r ? fn(r) : r));
    const current = upload;
    let normalized: Extract<AgentEvent, { type: "normalized" }> | undefined;
    try {
      const request = { image: { url: upload.url, data_url: upload.preview, name: upload.name }, action, image_id: labelImageId };
      for await (const event of streamPathology(request, controller.signal)) {
        if (event.type === "label_result") update((r) => ({ ...r, result: event }));
        else if (event.type === "quality_result") update((r) => ({ ...r, quality: event }));
        else if (event.type === "label_image") setLabelImageId(event.image_id);
        else if (event.type === "normalized") normalized = event;
        else if (event.type === "error") update((r) => ({ ...r, error: event.message }));
        else update((r) => ({ ...r, steps: applyEvent(r.steps, event) }));
      }
      if (normalized) {
        // Show the normalized copy in place of the original (which stays available to go back to)
        const file = await fetchImageFromUrl(normalized.url);
        const before = { upload: current, imageId: labelImageId };
        addFile(new File([file], normalized.name || file.name, { type: file.type }), true);
        setOriginal((o) => o ?? before);
        setLabelImageId(normalized.image_id);
        return;
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

  function restoreOriginal() {
    if (!original || busy) return;
    setUpload(original.upload);
    setRun(undefined);
    setLabelImageId(original.imageId);
    setOriginal(undefined);
  }

  /** Stream an AI interpretation of the image; "What to label" is passed along as context. */
  async function diagnose() {
    if (!upload?.url || !upload.preview || diagnosis?.pending) return;
    const controller = new AbortController();
    diagnoseAbort.current = controller;
    setDiagnosis({ text: "", pending: true });
    let found: Extract<AgentEvent, { type: "diagnosis_regions" }> | undefined;
    try {
      const request = { image: { url: upload.url, data_url: upload.preview, name: upload.name }, context: instructions };
      for await (const event of streamDiagnosis(request, controller.signal)) {
        if (event.type === "token") setDiagnosis((d) => d && { ...d, text: d.text + event.text });
        else if (event.type === "diagnosis_regions") {
          found = event;
          setDiagnosis((d) => d && { ...d, regions: event.regions, suspected: event.diagnosis });
        } else if (event.type === "error") setDiagnosis((d) => d && { ...d, error: event.message });
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setDiagnosis((d) => d && { ...d, error: (e as Error).message });
    } finally {
      setDiagnosis((d) => d && { ...d, pending: false });
      diagnoseAbort.current = null;
    }
    // Show the findings on the image: outline the areas the interpretation describes
    if (found?.regions.length && !controller.signal.aborted) {
      const areaModel: Model = found.medical ? "medsam" : "sam";
      // The leading diagnosis goes on the lesional area as one outline, visibly marked as AI-suspected;
      // the findings keep their descriptive labels
      // "Malignant melanoma" -> "Suspected malignant melanoma (AI)"; abbreviations such as "DCIS" keep their case
      const dx = /^[A-Z][a-z]/.test(found.diagnosis) ? found.diagnosis[0].toLowerCase() + found.diagnosis.slice(1) : found.diagnosis;
      const suspected = dx ? `Suspected ${dx} (AI)` : "";
      const lesion = suspected
        ? `First, one outline labelled "${suspected}" around the main abnormal area: ${found.lesion_area}. ` +
          "Use one box around that whole area (it may cover most of the image), confidence \"low\", and the note " +
          "\"AI interpretation, not a diagnosis: needs pathologist review\".\n"
        : "";
      setModel(areaModel);
      start({
        instructions:
          lesion +
          "Then outline the problematic regions behind these findings. For each finding, outline several clear " +
          "examples spread over the image (at least 3 when there are many, up to 20 outlines in all), each box " +
          "tight around one example. Put each finding's significance in the annotation notes.\n" +
          found.regions.map((r) => `- ${r.label}: ${r.description}. Significance: ${r.significance}`).join("\n"),
        labels: [...(suspected ? [suspected] : []), ...found.regions.map((r) => r.label)],
        model: areaModel,
      });
    }
  }

  return (
    <div className="label-view">
      <header className="label-intro">
        <h2><ScanSearch size={22} aria-hidden /> Annotate Images</h2>
        <p>
          Upload an image and say what to label. The Image Annotation Agent saves it in Image Label and finds each
          object; Segment Anything (or MedSAM for medical scans) traces its exact outline. Download the
          result as COCO or YOLO training data.
        </p>
      </header>

      {!available && (
        <p className="label-alert">
          <CircleAlert size={16} aria-hidden /> {unavailableReason ?? "The Image Annotation Agent isn't available on this server."}
        </p>
      )}

      <div className="label-grid">
        <section className="label-panel" aria-labelledby="label-image-heading">
          <h3 id="label-image-heading">1. Image</h3>
          <span className="label-source-title">Upload an image</span>
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
          <div className="label-or" role="separator" aria-label="or"><span>OR</span></div>
          <label className="label-source-title" htmlFor="label-image-url">Image URL</label>
          <form className="label-url" onSubmit={(e) => { e.preventDefault(); addUrl(imageUrl); }}>
            <Link2 size={15} aria-hidden />
            <input
              id="label-image-url"
              type="url"
              inputMode="url"
              value={imageUrl}
              placeholder="Paste an image address (https://…)"
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

          <div className="histology-tools">
            <span className="label-source-title"><Microscope size={14} aria-hidden /> Histology tools <em>(H&E-stained tissue)</em></span>
            <div className="histology-buttons">
              <button className="label-secondary" onClick={() => runTool("quality")} disabled={busy || upload?.status !== "ready" || !available}
                title="Tissue, blur, marker pen, exposure and staining checks">
                <Gauge size={15} aria-hidden /> Check quality
              </button>
              <button className="label-secondary" onClick={() => runTool("nuclei")} disabled={busy || upload?.status !== "ready" || !available}
                title="Find and outline every cell nucleus automatically (StarDist)">
                <ScanSearch size={15} aria-hidden /> Detect nuclei
              </button>
              <button className="label-secondary" onClick={() => runTool("normalize")} disabled={busy || upload?.status !== "ready" || !available}
                title="Standardise the pink and purple stain colours (Macenko); saved as a new image">
                <Palette size={15} aria-hidden /> Normalize stain
              </button>
            </div>
            <small className="label-hint">
              Automatic: no instructions needed. Nuclei detection works on H&E slides only; the first run after a quiet spell
              takes up to a minute while the model starts.
            </small>
            {original && (
              <p className="histology-normalized">
                Showing the stain-normalized copy (saved in Image Label as a new image).{" "}
                <button className="link-btn" onClick={restoreOriginal} disabled={busy}><Undo2 size={13} aria-hidden /> Back to the original</button>
              </p>
            )}
          </div>

          <div className="label-actions">
            {busy ? (
              <button className="label-run" onClick={() => abortRef.current?.abort()}>
                <Square size={14} aria-hidden /> Stop
              </button>
            ) : (
              <button className="label-run" onClick={() => start()} disabled={!canRun}>
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
          {!run && !diagnosis && <p className="label-empty">The annotated image appears here. Labeling usually takes 10 to 30 seconds.</p>}

          {/* The annotated image comes first: the interpretation below can be long */}
          <div ref={resultRef} className="label-result-anchor">
            {run?.result && upload?.preview && <LabelResultView result={run.result} image={upload.preview} name={upload.name} />}
          </div>
          {run?.quality && <QualityCard quality={run.quality} />}
          {run?.pending && (
            <p className="label-progress">
              <LoaderCircle size={15} className="spin" aria-hidden />
              {run.action ? PROGRESS[run.action] : diagnosis ? "Outlining the problematic regions on the image…" : "Annotating the image…"}
              <span>{run.action ? "a few seconds, up to a minute if the model is starting" : "usually 20 to 40 seconds"}</span>
            </p>
          )}
          {run?.error && <p className="label-alert"><CircleAlert size={16} aria-hidden /> {run.error}</p>}

          {diagnosis?.regions && diagnosis.regions.length > 0 && (
            <div className="diagnosis-regions">
              <h4>Problematic regions</h4>
              {diagnosis.suspected && (
                <p className="diagnosis-suspected">
                  Outlined as <strong>Suspected {diagnosis.suspected.replace(/^[A-Z](?=[a-z])/, (c) => c.toLowerCase())} (AI)</strong>: the AI's leading interpretation,
                  not a diagnosis. It needs confirmation by a pathologist.
                </p>
              )}
              {diagnosis.suspected && onFindTrials && (
                <div className="diagnosis-trials">
                  <button className="label-secondary" onClick={() => onFindTrials(diagnosis.suspected!)}>
                    <FlaskConical size={15} aria-hidden /> Find clinical trials
                  </button>
                  <span>
                    Opens the Clinical Trials search with {diagnosis.suspected} filled in: add your city, then search.
                    Finding trials doesn't confirm the diagnosis.
                  </span>
                </div>
              )}
              <ul>
                {diagnosis.regions.map((r) => (
                  <li key={r.label} title={r.description}><strong>{r.label}</strong>: {r.significance}</li>
                ))}
              </ul>
            </div>
          )}

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

          {run?.steps.map((step) => (step.type === "agent" ? <AgentCard key={step.id} step={step} /> : null))}
        </section>
      </div>
    </div>
  );
}

function LabelResultView({ result, image, name }: { result: LabelResult; image: string; name: string }) {
  const nuclei = result.nuclei_summary;
  const exportable = result.annotations.filter((a) => a.type === "polygon" || a.type === "circle").length;
  const base = name.replace(/\.[^.]+$/, "") || "image";
  const hasNuclei = result.annotations.some((a) => layerOf(a) === "nuclei");
  const hasOutlines = result.annotations.some((a) => layerOf(a) !== "nuclei");

  return (
    <div className="label-result">
      <AnnotatedImage annotations={result.annotations} image={image} name={name} width={result.width} height={result.height} />

      {nuclei && (
        <p className="nuclei-summary">
          <strong>{nuclei.count.toLocaleString()} nuclei</strong>
          {nuclei.returned < nuclei.count && ` (the ${nuclei.returned} most confident are outlined)`} ·{" "}
          {nuclei.per_megapixel.toLocaleString()} per megapixel · median area {nuclei.median_area} px² ·{" "}
          <span title="Spread of nuclear size (coefficient of variation): higher means more variable sizes, a rough sign of pleomorphism">
            size variation {nuclei.area_variation}
          </span>{" "}
          · {nuclei.enlarged} enlarged (over 2.5× the median area)
        </p>
      )}
      {result.annotations.length === 0 ? (
        <p className="label-alert"><CircleAlert size={16} aria-hidden /> {nuclei ? "No nuclei were found. Is this an H&E-stained tissue image?" : "The agent saved no annotations. Try more specific instructions."}</p>
      ) : (
        <p className="label-note">
          {hasOutlines && "Outlines are traced by Segment Anything from the agent's boxes; dashed ones scored low. Check that each outline is the right object before you train on it. "}
          {hasNuclei && "Nuclei are found automatically by StarDist, a model trained on H&E slides: measurements for research and datasets, not a diagnosis. "}
          Hover over a legend row to pick out its shapes; click it to hide them.
          {exportable < result.annotations.length && ` ${result.annotations.length - exportable} pin, arrow or rectangle shapes are left out of exports.`}
        </p>
      )}

      <section className="annotate-further" aria-labelledby="annotate-further-heading">
        <h4 id="annotate-further-heading"><PenTool size={15} aria-hidden /> Download and annotate further</h4>
        <div className="label-downloads">
          <button className="label-download" onClick={() => downloadDataUrl(image, `${base}.${image.startsWith("data:image/png") ? "png" : "jpg"}`)}>
            <Download size={14} aria-hidden /> Image
          </button>
          <button className="label-download" onClick={() => download(`${base}.coco.json`, JSON.stringify(result.exports.coco, null, 2), "application/json")} disabled={!exportable}>
            <Download size={14} aria-hidden /> Annotations (COCO)
          </button>
          <button className="label-download" onClick={() => downloadFigure(base)} disabled={!result.annotations.length}>
            <Download size={14} aria-hidden /> Annotated image (PNG)
          </button>
          <a className="label-download primary" href="https://labels.sachin-kale.com/" target="_blank" rel="noreferrer">
            <SquareArrowOutUpRight size={14} aria-hidden /> Open Image Label
          </a>
        </div>
        <ol>
          <li>Download the <strong>image</strong> and its <strong>annotations (COCO)</strong>.</li>
          <li>Open <a href="https://labels.sachin-kale.com/" target="_blank" rel="noreferrer">Image Label</a> and upload the image.</li>
          <li>Press <strong>Import</strong> in its toolbar and choose the COCO file: the outlines appear, ready to edit, add to and export again.</li>
        </ol>
      </section>

      <h4 className="label-downloads-title">Training data</h4>
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
        {result.exports.qupath !== undefined && (
          <button className="label-download" onClick={() => download(`${base}.geojson`, JSON.stringify(result.exports.qupath), "application/geo+json")}
            disabled={!result.annotations.length} title="For QuPath: File > Import objects">
            <Download size={14} aria-hidden /> QuPath GeoJSON
          </button>
        )}
      </div>

      {result.report && (
        <details className="label-report">
          <summary>Agent's report</summary>
          <div className="answer"><Markdown remarkPlugins={[remarkGfm]}>{result.report}</Markdown></div>
          <a className="label-download ask-ai" href="https://genetics.sachin-kale.com/" target="_blank" rel="noreferrer">
            <Sparkles size={14} aria-hidden /> Ask AI <SquareArrowOutUpRight size={13} aria-hidden />
          </a>
        </details>
      )}
      <p className="label-saved">
        Saved in <a href="https://labels.sachin-kale.com" target="_blank" rel="noreferrer">Image Label</a> as image{" "}
        <span className="mono">{result.image_id}</span> (in the shared agent account).
      </p>
    </div>
  );
}

function downloadDataUrl(dataUrl: string, filename: string) {
  Object.assign(document.createElement("a"), { href: dataUrl, download: filename }).click();
}

/** The annotated figure (image, outlines and callouts) as a PNG, drawn from the SVG on the page. */
async function downloadFigure(base: string) {
  const svg = document.querySelector<SVGSVGElement>(".annotated-figure");
  if (!svg) return;
  const clone = svg.cloneNode(true) as SVGSVGElement;
  // Styles from the stylesheet don't travel with the SVG: copy the ones that matter onto each element
  const live = svg.querySelectorAll("*");
  clone.querySelectorAll("*").forEach((el, i) => {
    const css = getComputedStyle(live[i]);
    for (const prop of ["fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "font-family", "font-weight", "font-size"]) {
      (el as SVGElement).style.setProperty(prop, css.getPropertyValue(prop));
    }
  });
  const { width, height } = svg.viewBox.baseVal;
  const scale = Math.max(1, 1600 / width); // at least 1600 px wide, so text stays sharp
  clone.setAttribute("width", String(width * scale));
  clone.setAttribute("height", String(height * scale));
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" }));
  const img = new Image();
  await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = url; });
  const canvas = Object.assign(document.createElement("canvas"), { width: width * scale, height: height * scale });
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  URL.revokeObjectURL(url);
  downloadDataUrl(canvas.toDataURL("image/png"), `${base}-annotated.png`);
}

function download(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const VERDICTS = {
  good: { text: "Good quality", icon: CircleCheck },
  check: { text: "Check before analysing", icon: TriangleAlert },
  poor: { text: "Poor quality", icon: CircleAlert },
} as const;

/** check_image_quality's verdict, warnings and the measurements behind them. */
function QualityCard({ quality }: { quality: QualityResult }) {
  const { text, icon: Icon } = VERDICTS[quality.verdict];
  const m = quality.metrics;
  return (
    <div className={`quality-card quality-${quality.verdict}`}>
      <h4><Icon size={16} aria-hidden /> {text}</h4>
      {quality.warnings.length ? (
        <ul>{quality.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      ) : (
        <p>Enough tissue, in focus, no marker pen, well exposed and well stained.</p>
      )}
      <p className="quality-metrics">
        Tissue {Math.round((m.tissue_fraction ?? 0) * 100)}% · sharpness {m.blur_score} · pen {((m.pen_fraction ?? 0) * 100).toFixed(1)}% ·
        stain saturation {m.stain_saturation}
      </p>
    </div>
  );
}
