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

/** Events streamed by the agent backend over SSE. `type` is the SSE event name. */
export type AgentEvent =
  | { type: "conversation"; id: string }
  | { type: "mcp_connected"; server_url: string; tools: string[] }
  | { type: "token"; text: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; output: unknown; is_error: boolean }
  | { type: "error"; message: string }
  | { type: "done" };

export interface McpInfo {
  server_url: string;
  model: string;
  tools: { name: string; description: string | null; input_schema: unknown }[];
  resources: string[];
  resource_templates: string[];
  prompts: { name: string; description: string | null }[];
}

export async function getMcpInfo(): Promise<McpInfo> {
  const res = await fetch(`${API_URL}/mcp/info`);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

/**
 * POST a message and read the Server-Sent Events response.
 *
 * The browser's EventSource only supports GET, so we read the SSE stream with fetch()
 * and parse the wire format ourselves: events are separated by a blank line, and each
 * has `event: <name>` and one or more `data: <json>` lines. Lines starting with ':' are
 * keep-alive comments. Aborting `signal` stops the stream (the Stop button).
 */
export async function* streamChat(
  message: string,
  conversationId: string | undefined,
  images: ChatImage[],
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message, conversation_id: conversationId, images }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);

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
