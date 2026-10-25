/**
 * Draws annotations so they don't bury each other, with each label named beside the image.
 *
 * Labels fall into three layers, always in the same order and style:
 *   AI interpretation  "Suspected … (AI)": a dashed amber outline, no fill, drawn underneath
 *   Findings           the agent's or user's labels: a palette colour with a light fill
 *   Nuclei             StarDist outlines: thin lines, no fill, drawn on top
 * Each label's name sits in a callout above or below the image, joined to every shape with that label by a
 * leader line; callouts are split evenly between the two bands and spaced in equal columns across each. Nuclei, which can
 * number hundreds, get no callouts: the legend names them. The legend lists every label with its colour
 * and count, grouped by layer.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import type { Annotation } from "../api";

export type Layer = "interpretation" | "findings" | "nuclei";

// Nuclei typed by Cell types (the label server's classify_cells) keep that tool's colours
const CELL_TYPE_COLORS: Record<string, string> = {
  "tumour cell": "#ff1744",
  "immune cell": "#2979ff",
  "connective tissue cell": "#00c853",
  "dead cell": "#9e9e9e",
  "normal epithelial cell": "#ffab00",
};

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
  count: number;
}

/** One entry per label, ordered by layer and then by size of the group (largest first). */
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
    .map(([label, { layer, count }]) => ({
      label,
      layer,
      count,
      color:
        layer === "interpretation" ? INTERPRETATION_COLOR
        : layer === "nuclei" ? (CELL_TYPE_COLORS[label] ?? (/enlarged/i.test(label) ? ENLARGED_COLOR : NUCLEUS_COLOR))
        : PALETTE[findings++ % PALETTE.length],
    }));
}

interface Point { x: number; y: number }

function points(a: Annotation): Point[] {
  if (a.type === "polygon" && a.points?.length) return a.points;
  if (a.type === "circle") {
    const r = a.radius ?? 0;
    return [{ x: (a.x ?? 0) - r, y: a.y ?? 0 }, { x: (a.x ?? 0) + r, y: a.y ?? 0 }, { x: a.x ?? 0, y: (a.y ?? 0) - r }];
  }
  if (a.type === "rectangle") {
    const x = a.x ?? 0, y = a.y ?? 0, w = a.width ?? 0, h = a.height ?? 0;
    return [{ x, y: y + h / 2 }, { x: x + w, y: y + h / 2 }];
  }
  return [{ x: a.x ?? 0, y: a.y ?? 0 }];
}

function center(a: Annotation): Point {
  const pts = points(a);
  return { x: avg(pts.map((p) => p.x)), y: avg(pts.map((p) => p.y)) };
}

/** Where a leader line meets a shape: its edge facing the callout's band. */
function edgeToward(a: Annotation, side: "top" | "bottom"): Point {
  return points(a).reduce((best, p) => ((side === "top" ? p.y < best.y : p.y > best.y) ? p : best));
}

function avg(values: number[]): number {
  return values.reduce((n, v) => n + v, 0) / Math.max(1, values.length);
}

export function wrap(text: string, maxChars: number, maxLines = 3): string[] {
  const lines: string[] = [];
  for (const word of text.split(/\s+/)) {
    const last = lines[lines.length - 1];
    if (last !== undefined && `${last} ${word}`.length <= maxChars) lines[lines.length - 1] = `${last} ${word}`;
    else lines.push(word);
  }
  if (lines.length > maxLines) {
    const rest = lines.slice(maxLines - 1).join(" ");
    lines.splice(maxLines - 1, lines.length, rest.length > maxChars ? `${rest.slice(0, maxChars - 1)}…` : rest);
  }
  return lines;
}

export interface Callout {
  entry: LabelEntry;
  side: "top" | "bottom";
  lines: string[];
  x: number; // box left edge, in figure units
  y: number; // box top, in figure units (the image starts at bandTop)
  width: number;
  height: number;
  targets: Point[]; // where the leader lines end, in figure units
}

/**
 * One callout per label, in a band above or below the image: labels whose shapes are in the upper half go
 * above, the rest below, keeping the two bands as even as possible; each band is divided into equal
 * columns, ordered left to right like the shapes, and every callout is joined to each of its shapes.
 * `scale` is screen pixels per image pixel, so text keeps a readable size however large the image is.
 */
export function layoutCallouts(groups: { entry: LabelEntry; shapes: Annotation[] }[], width: number, height: number, scale: number) {
  const font = 12 / scale;
  const lineHeight = font * 1.25;
  const pad = font * 0.5;
  const gutter = font * 1.6; // between the callouts and the image, where leaders bend
  const withCenters = groups
    .filter((g) => g.shapes.length)
    .map((g) => ({ ...g, c: { x: avg(g.shapes.map((s) => center(s).x)), y: avg(g.shapes.map((s) => center(s).y)) } }))
    .sort((a, b) => a.c.y - b.c.y);
  // Even bands: the upper half of the labels (by where their shapes are) above, the rest below
  const mid = Math.floor(withCenters.length / 2);
  const half = mid + (withCenters.length % 2 && withCenters[mid].c.y < height / 2 ? 1 : 0);
  const bands = { top: withCenters.slice(0, half), bottom: withCenters.slice(half) };
  const minColumn = font * 9;
  const sized = (["top", "bottom"] as const).map((side) => {
    const items = bands[side].sort((a, b) => a.c.x - b.c.x);
    const perRow = Math.max(1, Math.min(items.length, Math.floor(width / minColumn)));
    const columnWidth = width / perRow;
    const boxWidth = columnWidth - font * 0.8;
    const maxChars = Math.max(6, Math.floor((boxWidth - pad * 2) / (font * 0.55)));
    const rows: { g: (typeof items)[number]; lines: string[]; col: number }[][] = [];
    items.forEach((g, i) => {
      if (i % perRow === 0) rows.push([]);
      rows[rows.length - 1].push({ g, lines: wrap(g.entry.label + (g.shapes.length > 1 ? ` ×${g.shapes.length}` : ""), maxChars), col: i % perRow });
    });
    const rowHeights = rows.map((r) => Math.max(...r.map((b) => b.lines.length)) * lineHeight + pad * 2);
    const bandHeight = rows.length ? rowHeights.reduce((n, h) => n + h, 0) + font * 0.4 * (rows.length - 1) + gutter : 0;
    return { side, rows, rowHeights, columnWidth, boxWidth, perRow, bandHeight };
  });
  const [top, bottom] = sized;
  const imageTop = top.bandHeight;
  const callouts: Callout[] = [];
  for (const band of sized) {
    let y = band.side === "top" ? 0 : imageTop + height + gutter;
    band.rows.forEach((row, r) => {
      // A short last row is centred, so the band stays symmetric
      const offset = ((band.perRow - row.length) * band.columnWidth) / 2;
      for (const b of row) {
        callouts.push({
          entry: b.g.entry,
          side: band.side,
          lines: b.lines,
          x: offset + b.col * band.columnWidth + font * 0.4,
          y,
          width: band.boxWidth,
          height: band.rowHeights[r],
          targets: b.g.shapes.map((s) => {
            const p = edgeToward(s, band.side);
            return { x: p.x, y: p.y + imageTop };
          }),
        });
      }
      y += band.rowHeights[r] + font * 0.4;
    });
  }
  return { callouts, font, lineHeight, pad, imageTop, figureHeight: imageTop + height + bottom.bandHeight };
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
  const [focus, setFocus] = useState<string>(); // legend or callout hover: the other labels fade
  const [showCallouts, setShowCallouts] = useState(true);

  const stroke = Math.max(2, Math.max(width, height) / 300);
  const order = (a: Annotation) => LAYERS.findIndex((l) => l.id === byLabel.get(a.label)?.layer);
  // Interpretation underneath, findings, then nuclei on top; within a layer, larger shapes first
  const visible = annotations
    .filter((a) => !hidden.has(a.label))
    .sort((a, b) => order(a) - order(b) || area(b) - area(a));
  const groups = entries
    .filter((e) => e.layer !== "nuclei" && !hidden.has(e.label))
    .map((entry) => ({ entry, shapes: visible.filter((a) => a.label === entry.label) }));
  // Screen pixels per image pixel, so callout text stays about 12 px at any size
  const canvasRef = useRef<HTMLDivElement>(null);
  const [shownWidth, setShownWidth] = useState(width);
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([e]) => setShownWidth(e.contentRect.width || width));
    observer.observe(el);
    return () => observer.disconnect();
  }, [width]);
  const layout = layoutCallouts(showCallouts ? groups : [], width, height, Math.max(0.05, shownWidth / width));
  const faded = (label: string) => focus !== undefined && focus !== label;
  const lineWidth = Math.max(1.5, stroke * 0.8, 1.5 / Math.max(0.05, shownWidth / width));

  const toggle = (labels: string[]) =>
    setHidden((h) => {
      const next = new Set(h);
      const allHidden = labels.every((l) => next.has(l));
      for (const l of labels) allHidden ? next.delete(l) : next.add(l);
      return next;
    });

  return (
    <>
      <div className="label-canvas" ref={canvasRef}>
        <svg viewBox={`0 0 ${width} ${layout.figureHeight}`} role="img" aria-label={`${name} with ${annotations.length} annotations`} className="annotated-figure">
          <image href={image} x={0} y={layout.imageTop} width={width} height={height} preserveAspectRatio="none" />
          <g transform={`translate(0 ${layout.imageTop})`}>
            {visible.map((a) => (
              <Shape key={a.id} annotation={a} entry={byLabel.get(a.label)!} stroke={stroke} faded={faded(a.label)} />
            ))}
          </g>
          {layout.callouts.map((c) => {
            const startX = c.x + c.width / 2;
            const startY = c.side === "top" ? c.y + c.height : c.y;
            // Leaders run straight out of the callout to the image edge, then on to each shape
            const elbowY = c.side === "top" ? layout.imageTop : layout.imageTop + height;
            return (
              <g
                key={c.entry.label}
                className="callout"
                opacity={faded(c.entry.label) ? 0.15 : 1}
                onMouseEnter={() => setFocus(c.entry.label)}
                onMouseLeave={() => setFocus(undefined)}
              >
                {c.targets.map((t, i) => {
                  const d = `M ${startX} ${startY} L ${startX} ${elbowY} L ${t.x} ${t.y}`;
                  return (
                    <g key={i}>
                      <path d={d} className="leader-halo" strokeWidth={lineWidth * 3} />
                      <path d={d} stroke={c.entry.color} strokeWidth={lineWidth} fill="none" />
                      <circle cx={t.x} cy={t.y} r={lineWidth * 2.2} fill={c.entry.color} stroke="#fff" strokeWidth={lineWidth * 0.6} />
                    </g>
                  );
                })}
                <rect x={c.x} y={c.y} width={c.width} height={c.height} rx={layout.font * 0.35} className="callout-box" stroke={c.entry.color} strokeWidth={lineWidth} />
                <text fontSize={layout.font} className="callout-text">
                  {c.lines.map((line, i) => (
                    <tspan key={i} x={c.x + c.width / 2} y={c.y + layout.pad + layout.lineHeight * (i + 0.78)} textAnchor="middle">
                      {line}
                    </tspan>
                  ))}
                </text>
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
                    <span
                      className={id === "nuclei" ? "legend-badge ring" : "legend-badge"}
                      style={id === "nuclei" ? { borderColor: r.color } : { background: r.color }}
                    />
                    <span className="legend-name">{r.label}</span>
                    <span className="count">{r.count}</span>
                  </button>
                ))}
              </div>
            </section>
          );
        })}
        {groups.length > 0 && (
          <button className="link-btn legend-text" onClick={() => setShowCallouts(!showCallouts)}>
            {showCallouts ? <EyeOff size={13} aria-hidden /> : <Eye size={13} aria-hidden />} {showCallouts ? "Hide" : "Show"} label callouts
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
