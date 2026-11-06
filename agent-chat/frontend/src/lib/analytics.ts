import { API_URL } from "../api";

/**
 * First-party usage analytics: what the browser alone sees (views, uploads, downloads), sent to this site's own
 * API. Agent runs are recorded by the server. No cookies; the session id is per tab (sessionStorage) and random.
 * Nothing is sent when the browser asks not to be tracked (Do Not Track / Global Privacy Control).
 */

type Props = Record<string, string | number | boolean>;
export type ClientEvent = "view" | "upload" | "download";

const optedOut =
  (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl === true || navigator.doNotTrack === "1";

let fallbackSession: string | undefined;
function sessionId(): string {
  const fresh = () => crypto.randomUUID().replace(/-/g, "");
  try {
    let id = sessionStorage.getItem("analytics-session");
    if (!id) sessionStorage.setItem("analytics-session", (id = fresh()));
    return id;
  } catch {
    return (fallbackSession ??= fresh());
  }
}

let firstEvent = true;

export function track(name: ClientEvent, props: Props = {}) {
  if (optedOut) return;
  const body: Record<string, unknown> = { name, props, session: sessionId() };
  if (firstEvent) {
    // Where the visit came from: another site's address (the server keeps only its host), and ?utm_source=
    firstEvent = false;
    try {
      if (document.referrer && new URL(document.referrer).hostname !== location.hostname) body.referrer = document.referrer;
    } catch { /* not a URL */ }
    const utm = new URLSearchParams(location.search).get("utm_source");
    if (utm && /^[\w .-]{1,60}$/.test(utm)) body.utm_source = utm;
  }
  fetch(`${API_URL}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: true, // still delivered if the page is closing
  }).catch(() => {});
}

let lastView: string | undefined;

/** One view per change of view (the hash routes); repeated calls for the same view are ignored. */
export function trackView(view: string) {
  if (view === lastView) return;
  lastView = view;
  track("view", { view });
}

/** The export format, from the downloaded file's name. */
export function trackDownload(filename: string) {
  const format =
    filename === "classes.txt" ? "yolo_classes"
    : filename.endsWith(".coco.json") ? "coco"
    : filename.endsWith(".txt") ? "yolo"
    : filename.endsWith(".geojson") ? "qupath"
    : filename.endsWith("-annotated.png") ? "figure"
    : /\.(png|jpe?g|webp|gif)$/.test(filename) ? "image"
    : "other";
  track("download", { format });
}
