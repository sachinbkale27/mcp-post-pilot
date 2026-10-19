/** How agent tool calls are presented: kind, icon and plain-language labels. */
import {
  BookOpen, FilePen, FilePlus2, FileSearch, List, type LucideIcon, Send, Trash2, Undo2, Wrench,
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
const quoted = (v: unknown) => (typeof v === "string" && v ? `“${v.length > 48 ? v.slice(0, 47) + "…" : v}”` : "");

const TOOLS: Record<string, ToolMeta> = {
  list_posts: {
    kind: "read", icon: List,
    running: (a) => `Listing ${a.status ? `${a.status} ` : ""}posts`,
    done: (a) => `Listed ${a.status ? `${a.status} ` : ""}posts`,
  },
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
};

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
  const value = output && typeof output === "object" && "result" in output ? (output as { result: unknown }).result : output;
  if (Array.isArray(value)) return `${value.length} ${value.length === 1 ? "result" : "results"}`;
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (typeof o.title === "string") return o.status ? `${o.title} · ${o.status}` : o.title;
  }
  if (typeof value === "string") return value.length > 60 ? value.slice(0, 59) + "…" : value;
  return undefined;
}

export function formatDuration(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
