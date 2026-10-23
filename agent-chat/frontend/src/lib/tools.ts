/** How agent tool calls are presented: kind, icon and plain-language labels. */
import type { Trial } from "../api";
import {
  BookOpen, ChartColumn, ClipboardList, FlaskConical, MapPin, Dna, Eraser, FileDown, FilePen, FilePlus2, FileSearch, FileText, Globe, ImageUp, Images, Library, Link2, List,
  type LucideIcon, Microscope, PenTool, Replace, ScanSearch, SearchCheck, Send, Tags, Trash2, Undo2, WandSparkles, Wrench,
} from "lucide-react";

export type ToolKind = "read" | "write" | "destructive";

interface ToolMeta {
  kind: ToolKind;
  icon: LucideIcon;
  running: (args: Args) => string;
  done: (args: Args) => string;
}

type Args = Record<string, unknown>;

const post = (a: Args) => (a.post_id !== undefined ? `post #${a.post_id}` : "post");
const site = (v: unknown) => {
  try {
    return new URL(String(v)).host.replace(/^www\./, "");
  } catch {
    return "a page";
  }
};
const count = (v: unknown, noun: string) => (Array.isArray(v) ? `${v.length} ${noun}${v.length === 1 ? "" : "s"}` : `${noun}s`);
const where = (a: Args) => {
  const near = a.near as { place?: string } | undefined;
  return near?.place ? ` near ${near.place}` : a.country ? ` in ${a.country}` : "";
};
const quoted = (v: unknown) => (typeof v === "string" && v ? `“${v.length > 48 ? v.slice(0, 47) + "…" : v}”` : "");

const TOOLS: Record<string, ToolMeta> = {
  list_posts: {
    kind: "read", icon: List,
    running: (a) => `Listing ${a.status ? `${a.status} ` : ""}posts${a.category ? ` in ${a.category}` : ""}`,
    done: (a) => `Listed ${a.status ? `${a.status} ` : ""}posts${a.category ? ` in ${a.category}` : ""}`,
  },
  list_categories: { kind: "read", icon: Tags, running: () => "Checking categories", done: () => "Checked categories" },
  search_posts: {
    kind: "read", icon: FileSearch,
    running: (a) => `Searching posts for ${quoted(a.query)}`,
    done: (a) => `Searched posts for ${quoted(a.query)}`,
  },
  get_post: { kind: "read", icon: BookOpen, running: (a) => `Reading ${post(a)}`, done: (a) => `Read ${post(a)}` },
  create_post: {
    kind: "write", icon: FilePlus2,
    running: (a) => `Creating draft ${quoted(a.title)}`,
    done: (a) => `Created draft ${quoted(a.title)}`,
  },
  update_post: { kind: "write", icon: FilePen, running: (a) => `Updating ${post(a)}`, done: (a) => `Updated ${post(a)}` },
  publish_post: { kind: "write", icon: Send, running: (a) => `Publishing ${post(a)}`, done: (a) => `Published ${post(a)}` },
  unpublish_post: { kind: "write", icon: Undo2, running: (a) => `Unpublishing ${post(a)}`, done: (a) => `Unpublished ${post(a)}` },
  delete_post: { kind: "destructive", icon: Trash2, running: (a) => `Deleting ${post(a)}`, done: (a) => `Deleted ${post(a)}` },
  generate_image: {
    kind: "write", icon: WandSparkles,
    running: () => "Generating an image",
    done: () => "Generated an image",
  },
  // genetics MCP server
  search_clinvar: {
    kind: "read", icon: Microscope,
    running: (a) => `Searching ClinVar for ${[a.gene, a.query].filter(Boolean).join(" ")}`,
    done: (a) => `Searched ClinVar for ${[a.gene, a.query].filter(Boolean).join(" ")}`,
  },
  variant_frequencies: {
    kind: "read", icon: ChartColumn,
    running: (a) => `Looking up gnomAD frequencies of ${a.rsid}`,
    done: (a) => `Looked up gnomAD frequencies of ${a.rsid}`,
  },
  gene_info: { kind: "read", icon: Dna, running: (a) => `Reading about ${a.symbol}`, done: (a) => `Read about ${a.symbol}` },
  search_pubmed: {
    kind: "read", icon: Library,
    running: (a) => `Searching PubMed for ${quoted(a.query)}`,
    done: (a) => `Searched PubMed for ${quoted(a.query)}`,
  },
  get_pubmed_abstract: {
    kind: "read", icon: FileText,
    running: (a) => `Reading PMID ${a.pmid}`,
    done: (a) => `Read PMID ${a.pmid}`,
  },
  analyze_sequence: { kind: "read", icon: Dna, running: () => "Analyzing a sequence", done: () => "Analyzed a sequence" },
  // label-image MCP server
  list_images: {
    kind: "read", icon: Images,
    running: (a) => `Listing images${a.category ? ` in ${a.category}` : ""}`,
    done: (a) => `Listed images${a.category ? ` in ${a.category}` : ""}`,
  },
  get_image: { kind: "read", icon: BookOpen, running: () => "Reading an image", done: () => "Read an image" },
  update_image_metadata: { kind: "write", icon: FilePen, running: () => "Updating image details", done: () => "Updated image details" },
  upload_image_from_url: { kind: "write", icon: ImageUp, running: () => "Uploading an image", done: () => "Uploaded an image" },
  upload_image: { kind: "write", icon: ImageUp, running: () => "Uploading an image", done: () => "Uploaded an image" },
  add_annotations: {
    kind: "write", icon: PenTool,
    running: (a) => `Adding ${Array.isArray(a.annotations) ? a.annotations.length : ""} annotations`,
    done: (a) => `Added ${Array.isArray(a.annotations) ? a.annotations.length : ""} annotations`,
  },
  segment_objects: {
    kind: "write", icon: ScanSearch,
    running: (a) => `Tracing ${count(a.objects, "outline")}${a.model === "medsam" ? " with MedSAM" : ""}`,
    done: (a) => `Traced ${count(a.objects, "outline")}${a.model === "medsam" ? " with MedSAM" : ""}`,
  },
  detect_nuclei: { kind: "write", icon: ScanSearch, running: () => "Finding nuclei with StarDist", done: () => "Found nuclei with StarDist" },
  check_image_quality: { kind: "read", icon: SearchCheck, running: () => "Checking image quality", done: () => "Checked image quality" },
  normalize_stain: { kind: "write", icon: WandSparkles, running: () => "Normalizing the stain colours", done: () => "Normalized the stain colours" },
  warm_up_pathology: { kind: "read", icon: Wrench, running: () => "Starting the nuclei model", done: () => "Started the nuclei model" },
  replace_annotations: { kind: "destructive", icon: Replace, running: () => "Replacing annotations", done: () => "Replaced annotations" },
  remove_annotations: { kind: "destructive", icon: Eraser, running: () => "Removing annotations", done: () => "Removed annotations" },
  export_annotations: {
    kind: "read", icon: FileDown,
    running: (a) => `Exporting ${String(a.format ?? "coco").toUpperCase()}`,
    done: (a) => `Exported ${String(a.format ?? "coco").toUpperCase()}`,
  },
  // trials MCP server (Clinical Trials agent)
  search_trials: {
    kind: "read", icon: FlaskConical,
    running: (a) => `Searching trials for ${quoted(a.condition)}${where(a)}`,
    done: (a) => `Searched trials for ${quoted(a.condition)}${where(a)}`,
  },
  get_trial: { kind: "read", icon: BookOpen, running: (a) => `Reading ${a.nct_id}`, done: (a) => `Read ${a.nct_id}` },
  trial_locations: {
    kind: "read", icon: MapPin,
    running: (a) => `Finding sites of ${a.nct_id}`,
    done: (a) => `Found sites of ${a.nct_id}`,
  },
  submit_trials: {
    kind: "read", icon: ClipboardList,
    running: (a) => `Filing ${count(a.trials, "trial")}`,
    done: (a) => `Filed ${count(a.trials, "trial")}`,
  },
  // research MCP server (fact-check agent)
  web_search: {
    kind: "read", icon: SearchCheck,
    running: (a) => `Searching the web for ${quoted(a.query)}`,
    done: (a) => `Searched the web for ${quoted(a.query)}`,
  },
  fetch_page: {
    kind: "read", icon: Globe,
    running: (a) => `Reading ${site(a.url)}${a.focus ? ` for ${quoted(a.focus)}` : ""}`,
    done: (a) => `Read ${site(a.url)}${a.focus ? ` for ${quoted(a.focus)}` : ""}`,
  },
  check_links: {
    kind: "read", icon: Link2,
    running: (a) => `Checking ${count(a.urls, "link")}`,
    done: (a) => `Checked ${count(a.urls, "link")}`,
  },
};

/** The /media/... image URL in a tool result, if any (generate_image returns one). */
export function resultImage(output: unknown): string | undefined {
  const url = output && typeof output === "object" ? (output as Record<string, unknown>).url : undefined;
  return typeof url === "string" && /^\/media\/[\w.-]+\.(png|jpe?g|webp|gif)$/.test(url) ? url : undefined;
}

/** Known tools get friendly labels; anything else (another MCP server) falls back to its name. */
export function toolMeta(name: string): ToolMeta {
  return TOOLS[name] ?? {
    kind: /^(list|get|search|read|find)/.test(name) ? "read" : /^(delete|remove|drop)/.test(name) ? "destructive" : "write",
    icon: Wrench,
    running: () => `Calling ${name}`,
    done: () => `Called ${name}`,
  };
}

/** A short summary of a tool result for the collapsed card, e.g. "3 posts". */
export function summarizeResult(output: unknown): string | undefined {
  if (output && typeof output === "object" && Array.isArray((output as { trials?: unknown }).trials)) {
    const o = output as { total?: number; trials: unknown[] };
    return typeof o.total === "number" ? `${o.total} matching` : `${o.trials.length} trial${o.trials.length === 1 ? "" : "s"}`;
  }
  const value = output && typeof output === "object" && "result" in output ? (output as { result: unknown }).result : output;
  if (Array.isArray(value)) return `${value.length} ${value.length === 1 ? "result" : "results"}`;
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (typeof o.title === "string") return o.status ? `${o.title} · ${o.status}` : o.title;
    if (typeof o.symbol === "string" && typeof o.location === "string") return `${o.symbol} · ${o.location}`;
    if (typeof o.gc_percent === "number") return `${o.length} bases · ${o.gc_percent}% GC`;
    if (resultImage(o)) return `${o.size ?? "image"} · ${o.model ?? "AI"}`;
  }
  if (typeof value === "string") return value.length > 60 ? value.slice(0, 59) + "…" : value;
  return undefined;
}

/** What an agent filed with submit_trials (its last accepted call), for the trial cards. */
export function filedTrials(tools: { name: string; output?: unknown; isError?: boolean }[]): { trials: Trial[]; notes: string[] } | undefined {
  const filed = [...tools].reverse().find((t) => t.name === "submit_trials" && !t.isError && t.output);
  const out = filed && typeof filed.output === "object" ? (filed.output as { trials?: Trial[]; notes?: string[] }) : undefined;
  return out && Array.isArray(out.trials) ? { trials: out.trials, notes: Array.isArray(out.notes) ? out.notes : [] } : undefined;
}

export function formatDuration(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
