const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8102";
export const BLOG_URL = import.meta.env.VITE_BLOG_URL ?? "http://localhost:5173";
// The blog API stores uploaded images (same CloudFront distribution in production).
const BLOG_API_URL = import.meta.env.VITE_BLOG_API_URL ?? "http://localhost:8100";

/** An image attached to a chat message: its public URL plus a small copy the model can see. */
export interface ChatImage {
  url: string;
  data_url: string;
  name?: string;
}

/** Upload an (already resized) image; returns its public /media/... URL. */
export async function uploadImage(blob: Blob): Promise<string> {
  const res = await fetch(`${BLOG_API_URL}/images`, { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ?? `Upload failed (${res.status})`);
  return body.url;
}

/** Start loading the segmentation model (best effort; it takes a minute or two after a quiet spell). */
export function warmUpLabeling(model: "sam" | "medsam" = "sam") {
  fetch(`${API_URL}/label/warmup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  }).catch(() => {});
}

/** Download an image from a web address (through the agent API: browsers can't read most sites' images). */
export async function fetchImageFromUrl(url: string): Promise<File> {
  const res = await fetch(`${API_URL}/fetch-image`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail;
    throw new Error(typeof detail === "string" ? detail : `Could not load the image (${res.status})`);
  }
  const blob = await res.blob();
  return new File([blob], res.headers.get("x-image-name") ?? "image", { type: blob.type });
}

/**
 * Events streamed by the agent backend over SSE. `type` is the SSE event name.
 * agent_start/agent_end wrap each delegation from the supervisor to a specialist agent; the
 * specialist's tool calls carry `agent` and `delegation` (the agent_start id) to nest under it.
 */
export type AgentEvent =
  | { type: "conversation"; id: string }
  | { type: "agents"; agents: { name: string; title: string }[] }
  | { type: "token"; text: string }
  | { type: "agent_start"; id: string; agent: string; title: string; task: string }
  | { type: "agent_end"; id: string; agent: string; is_error: boolean }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown>; agent: string; delegation: string }
  | { type: "tool_result"; id: string; name: string; output: unknown; is_error: boolean; agent: string; delegation: string }
  | ({ type: "label_result" } & LabelResult)
  | { type: "label_image"; image_id: string }
  | ({ type: "quality_result" } & QualityResult)
  | { type: "normalized"; image_id: string; name: string; url: string }
  | { type: "diagnosis_regions"; medical: boolean; regions: DiagnosisRegion[]; diagnosis: string; lesion_area: string }
  | { type: "trials_report"; report: string }
  | { type: "drug_report"; report: string }
  | { type: "error"; message: string }
  | { type: "done" };

/** A trial the Clinical Trials agent filed (submit_trials): registry facts plus why it matched. */
export interface Trial {
  nct_id: string;
  title: string;
  status: string;
  phases: string[];
  conditions: string[];
  interventions: string[];
  enrollment?: number | null;
  sponsor: string;
  sponsor_type: string;
  ages: string;
  sex: string;
  last_update: string;
  why_stopped: string;
  has_results: boolean;
  site_count: number;
  nearest_site: { facility: string; city: string; country: string; status: string; distance_km?: number } | null;
  url: string;
  why_matched: string;
  evidence?: string;
  to_confirm: string[];
}

/** A problematic area found by Diagnose, outlined on the image by the Image Annotation Agent. */
export interface DiagnosisRegion {
  label: string;
  description: string;
  significance: string;
}

/** One annotation as Image Label stores it (image pixels, origin top-left). */
export interface Annotation {
  id: string;
  type: "polygon" | "circle" | "rectangle" | "pin" | "arrow";
  label: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  radius?: number;
  points?: { x: number; y: number }[];
  arrowTarget?: { x: number; y: number };
  confidence?: "high" | "medium" | "low";
  notes?: string;
}

/** What the Image Annotation Agent produced for one image (the label_result event). */
export interface LabelResult {
  image_id: string;
  width: number;
  height: number;
  annotations: Annotation[];
  report: string;
  exports: { coco: unknown; yolo: { classes: string[]; annotations: string }; qupath?: unknown };
  nuclei_summary?: NucleiSummary; // when the result came from detect_nuclei
  cell_types?: CellTypes; // when the result came from classify_cells
}

/** classify_cells' result (HoVer-Net, PanNuke weights: research and education only). */
export interface CellTypes {
  classified: number;
  counts: Record<string, number>;
  percent: Record<string, number>;
  immune_to_tumour: number | null;
  note: string;
  warning?: string; // the image was coarser than the model expects
}

/** detect_nuclei's measurements (StarDist). */
export interface NucleiSummary {
  count: number;
  per_megapixel: number;
  median_area: number;
  area_variation: number;
  enlarged: number;
  returned: number;
}

/** check_image_quality's verdict, measurements and plain-language warnings. */
export interface QualityResult {
  verdict: "good" | "check" | "poor";
  warnings: string[];
  metrics: Record<string, number>;
}

export type PathologyAction = "nuclei" | "quality" | "normalize" | "cells";

/** One specialist agent and what its MCP server advertises. */
export interface AgentInfo {
  name: string;
  title: string;
  description: string;
  server_url: string;
  online: boolean;
  error?: string;
  tools?: { name: string; description: string | null; input_schema: unknown }[];
  resources?: string[];
  resource_templates?: string[];
  prompts?: { name: string; description: string | null }[];
}

export interface AgentsInfo {
  model: string;
  agents: AgentInfo[];
}

/**
 * The configured agents and their MCP servers. Retries with backoff: on serverless the first
 * request after a deploy or an idle period can fail or be slow while the Lambdas cold-start.
 */
export async function getAgents(attempts = 4): Promise<AgentsInfo> {
  let lastError: Error = new Error("Cannot reach the agent");
  for (let i = 0; i < attempts; i++) {
    if (i > 0) await new Promise((r) => setTimeout(r, 1500 * 2 ** (i - 1)));
    try {
      const res = await fetch(`${API_URL}/agents`);
      if (res.ok) return res.json();
      lastError = new Error((await res.json().catch(() => ({}))).detail ?? `${res.status} ${res.statusText}`);
    } catch (e) {
      lastError = e as Error;
    }
  }
  throw lastError;
}

/**
 * POST a message and read the Server-Sent Events response. Aborting `signal` stops the stream (the Stop button).
 */
export function streamChat(
  message: string,
  conversationId: string | undefined,
  images: ChatImage[],
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  return streamEvents("/chat", { message, conversation_id: conversationId, images }, signal);
}

/** Upload one image to Image Label and have the Image Annotation Agent annotate it; ends with a label_result event. */
export function streamLabel(
  request: { image: ChatImage; instructions: string; labels: string[]; grid_step?: number; model?: "sam" | "medsam"; image_id?: string },
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  return streamEvents("/label", request, signal);
}

/** Run the Clinical Trials agent on one search; the trials are in its submit_trials result. */
export function streamTrials(request: { question: string; person: string }, signal: AbortSignal): AsyncGenerator<AgentEvent> {
  return streamEvents("/trials", request, signal);
}

/** Run the Drug Information agent on one question; its answer is the drug_report event. */
export function streamDrugs(request: { question: string }, signal: AbortSignal): AsyncGenerator<AgentEvent> {
  return streamEvents("/drugs", request, signal);
}

export const GENETICS_URL = import.meta.env.VITE_GENETICS_URL ?? "https://genetics.sachin-kale.com";

/** A summary of an image analysis for genetics.sachin-kale.com's assistant ("Ask AI"). */
export interface ResultsHandoff {
  image_url?: string;
  figure_url?: string; // the annotated figure, uploaded for the handoff
  image_name: string;
  suspected_diagnosis: string;
  findings: { label: string; count: number; significance: string; box?: number[] }[];
  nuclei?: NucleiSummary;
  quality?: { verdict: QualityResult["verdict"]; warnings: string[] };
  interpretation: string;
  report: string;
}

/** Hand the summary to the genetics assistant (through this site's server, which holds the handoff key);
 * returns the address that opens a chat about it. */
export async function handOffResults(results: ResultsHandoff): Promise<string> {
  const res = await fetch(`${API_URL}/handoff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(results),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Could not hand the results over (${res.status})`);
  return body.url;
}

/** Run one histopathology tool (StarDist nuclei, quality check, stain normalization) on an image. */
export function streamPathology(
  request: { image: ChatImage; action: PathologyAction; image_id?: string },
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  return streamEvents("/label/pathology", request, signal);
}

/** Stream an AI interpretation of one image (token events; research and education, not a diagnosis). */
export function streamDiagnosis(request: { image: ChatImage; context: string }, signal: AbortSignal): AsyncGenerator<AgentEvent> {
  return streamEvents("/diagnose", request, signal);
}

/**
 * The browser's EventSource only supports GET, so we read the SSE stream with fetch()
 * and parse the wire format ourselves: events are separated by a blank line, and each
 * has `event: <name>` and one or more `data: <json>` lines. Lines starting with ':' are
 * keep-alive comments.
 */
async function* streamEvents(path: string, body: unknown, signal: AbortSignal): AsyncGenerator<AgentEvent> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const detail = (await res.json().catch(() => ({}))).detail;
    throw new Error(Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : `${res.status} ${res.statusText}`);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop()!;
    for (const block of blocks) {
      const event = parseSseEvent(block);
      if (event) yield event;
    }
  }
}

function parseSseEvent(block: string): AgentEvent | undefined {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return undefined; // comment / keep-alive only
  return { type: name, ...JSON.parse(data.join("\n")) } as AgentEvent;
}

export function resetChat(conversationId: string) {
  return fetch(`${API_URL}/chat/${conversationId}`, { method: "DELETE" });
}
