/**
 * Draws annotations so they don't bury each other, and lists them in an orderly legend.
 *
 * Labels fall into three layers, always in the same order and style:
 *   AI interpretation  "Suspected … (AI)": a dashed amber outline, no fill, drawn underneath
 *   Findings           the agent's or user's labels: a palette colour with a light fill
 *   Nuclei             StarDist outlines: thin lines, no fill, drawn on top
 * Shapes carry a small numbered badge instead of their name (badges that would overlap are left out),
 * and the legend gives each number its name, colour and count, grouped by layer.
 */
import { useMemo, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import type { Annotation } from "../api";

export type Layer = "interpretation" | "findings" | "nuclei";

const LAYERS: { id: Layer; title: string }[] = [
  { id: "interpretation", title: "AI interpretation" },
  { id: "findings", title: "Findings" },
  { id: "nuclei", title: "Nuclei" },
];

// Findings colours, distinct on dark and light themes; amber, cyan and rose are kept for the other layers
const PALETTE = ["#2dd4bf", "#a78bfa", "#38bdf8", "#84cc16", "#ec4899", "#fb923c", "#818cf8", "#facc15"];
const INTERPRETATION_COLOR = "#f59e0b";
const NUCLEUS_COLOR = "#22d3ee";
const ENLARGED_COLOR = "#f43f5e";

export function layerOf(a: Annotation): Layer {
  if (/^suspected\b/i.test(a.label) || /\(AI\)\s*$/.test(a.label)) return "interpretation";
  if ((a.notes ?? "").includes("StarDist") || /^(enlarged )?nucleus$/i.test(a.label)) return "nuclei";
  return "findings";
}

export interface LabelEntry {
  label: string;
  layer: Layer;
  color: string;
  number: number; // badge number, in legend order
  count: number;
}

/** One entry per label, ordered by layer and then by size of the group (largest first), numbered 1, 2, … */
export function organize(annotations: Annotation[]): LabelEntry[] {
  const counts = new Map<string, { layer: Layer; count: number }>();
  for (const a of annotations) {
    const entry = counts.get(a.label) ?? { layer: layerOf(a), count: 0 };
    entry.count += 1;
    counts.set(a.label, entry);
  }
  const order = (l: Layer) => LAYERS.findIndex((x) => x.id === l);
  let findings = 0;
  return [...counts.entries()]
    .sort(([la, a], [lb, b]) => order(a.layer) - order(b.layer) || b.count - a.count || la.localeCompare(lb))
    .map(([label, { layer, count }], i) => ({
      label,
      layer,
      count,
      number: i + 1,
      color:
        layer === "interpretation" ? INTERPRETATION_COLOR
        : layer === "nuclei" ? (/enlarged/i.test(label) ? ENLARGED_COLOR : NUCLEUS_COLOR)
        : PALETTE[findings++ % PALETTE.length],
    }));
}

function anchorOf(a: Annotation): { x: number; y: number } {
  if (a.type === "polygon" && a.points?.length) {
    // The topmost point: the badge sits on the outline's upper edge, clear of its inside
    return a.points.reduce((top, p) => (p.y < top.y ? p : top), a.points[0]);
  }
  if (a.type === "circle") return { x: a.x ?? 0, y: (a.y ?? 0) - (a.radius ?? 0) };
  return { x: a.x ?? 0, y: a.y ?? 0 };
}

/** Badge positions: one per shape, skipping any that would overlap a badge already placed. */
export function placeBadges(annotations: Annotation[], radius: number, width: number, height: number) {
  const placed: { id: string; x: number; y: number }[] = [];
  for (const a of annotations) {
    const p = anchorOf(a);
    const x = Math.min(Math.max(p.x, radius), width - radius);
    const y = Math.min(Math.max(p.y, radius), height - radius);
    if (placed.every((b) => Math.hypot(b.x - x, b.y - y) >= radius * 2.4)) placed.push({ id: a.id, x, y });
  }
  return placed;
}

interface Props {
  annotations: Annotation[];
  image: string;
  name: string;
  width: number;
  height: number;
}

export function AnnotatedImage({ annotations, image, name, width, height }: Props) {
  const entries = useMemo(() => organize(annotations), [annotations]);
  const byLabel = useMemo(() => new Map(entries.map((e) => [e.label, e])), [entries]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState<string>(); // legend hover: the other labels fade
  const [badges, setBadges] = useState(true);

  const size = Math.max(width, height);
  const stroke = Math.max(2, size / 300);
  const radius = Math.max(9, size / 70);
  const order = (a: Annotation) => LAYERS.findIndex((l) => l.id === byLabel.get(a.label)?.layer);
  // Interpretation underneath, findings, then nuclei on top; within a layer, larger shapes first
  const visible = annotations
    .filter((a) => !hidden.has(a.label))
    .sort((a, b) => order(a) - order(b) || area(b) - area(a));
  // Nuclei get no badges: there can be hundreds, and the legend names them
  const placed = placeBadges(visible.filter((a) => byLabel.get(a.label)?.layer !== "nuclei"), radius, width, height);

  const toggle = (labels: string[]) =>
    setHidden((h) => {
      const next = new Set(h);
      const allHidden = labels.every((l) => next.has(l));
      for (const l of labels) allHidden ? next.delete(l) : next.add(l);
      return next;
    });

  return (
    <>
      <div className="label-canvas">
        <img src={image} alt={`${name} with ${annotations.length} annotations`} />
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden>
          {visible.map((a) => {
            const entry = byLabel.get(a.label)!;
            return (
              <Shape key={a.id} annotation={a} entry={entry} stroke={stroke} faded={focus !== undefined && focus !== a.label} />
            );
          })}
          {badges && placed.map((b) => {
            const entry = byLabel.get(visible.find((a) => a.id === b.id)!.label)!;
            return (
              <g key={b.id} className="shape-badge" opacity={focus && focus !== entry.label ? 0.15 : 1}>
                <circle cx={b.x} cy={b.y} r={radius} fill={entry.color} />
                <text x={b.x} y={b.y} fontSize={radius * 1.15} textAnchor="middle" dominantBaseline="central">{entry.number}</text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="legend">
        {LAYERS.map(({ id, title }) => {
          const rows = entries.filter((e) => e.layer === id);
          if (!rows.length) return null;
          const labels = rows.map((r) => r.label);
          const off = labels.every((l) => hidden.has(l));
          return (
            <section key={id} className="legend-group">
              <button className="legend-group-head" onClick={() => toggle(labels)} aria-pressed={!off}>
                {off ? <EyeOff size={13} aria-hidden /> : <Eye size={13} aria-hidden />} {title}
                <span className="count">{rows.reduce((n, r) => n + r.count, 0)}</span>
              </button>
              <div className="legend-rows">
                {rows.map((r) => (
                  <button
                    key={r.label}
                    className={hidden.has(r.label) ? "legend-row off" : "legend-row"}
                    onClick={() => toggle([r.label])}
                    onMouseEnter={() => setFocus(r.label)}
                    onMouseLeave={() => setFocus(undefined)}
                    onFocus={() => setFocus(r.label)}
                    onBlur={() => setFocus(undefined)}
                    aria-pressed={!hidden.has(r.label)}
                    title={`${r.label}: click to ${hidden.has(r.label) ? "show" : "hide"}`}
                  >
                    {id === "nuclei" ? <span className="legend-badge ring" style={{ borderColor: r.color }} /> : (
                      <span className="legend-badge" style={{ background: r.color }}>{r.number}</span>
                    )}
                    <span className="legend-name">{r.label}</span>
                    <span className="count">{r.count}</span>
                  </button>
                ))}
              </div>
            </section>
          );
        })}
        {placed.length > 0 && (
          <button className="link-btn legend-text" onClick={() => setBadges(!badges)}>
            {badges ? <EyeOff size={13} aria-hidden /> : <Eye size={13} aria-hidden />} {badges ? "Hide" : "Show"} numbers
          </button>
        )}
      </div>
    </>
  );
}

function area(a: Annotation): number {
  if (a.type === "circle") return Math.PI * (a.radius ?? 0) ** 2;
  return (a.width ?? 0) * (a.height ?? 0);
}

function Shape({ annotation: a, entry, stroke, faded }: { annotation: Annotation; entry: LabelEntry; stroke: number; faded: boolean }) {
  const { color, layer } = entry;
  const style = {
    stroke: color,
    strokeWidth: layer === "nuclei" ? Math.max(1, stroke * 0.6) : layer === "interpretation" ? stroke * 1.4 : stroke,
    fill: layer === "findings" && a.type !== "arrow" ? `${color}2e` : /enlarged/i.test(a.label) ? `${color}40` : "none",
    strokeDasharray:
      layer === "interpretation" ? `${stroke * 5} ${stroke * 3}`
      : a.confidence === "low" && layer === "findings" ? `${stroke * 3} ${stroke * 2}` : undefined,
    opacity: faded ? 0.15 : 1,
  };
  let shape;
  switch (a.type) {
    case "polygon":
      shape = <polygon points={(a.points ?? []).map((p) => `${p.x},${p.y}`).join(" ")} {...style} />;
      break;
    case "circle":
      shape = <circle cx={a.x} cy={a.y} r={a.radius} {...style} />;
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
    </g>
  );
}
