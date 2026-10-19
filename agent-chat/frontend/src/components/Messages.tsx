import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, ChevronRight, CircleAlert, Copy, LoaderCircle, OctagonX, PlugZap } from "lucide-react";
import { formatDuration, resultImage, summarizeResult, toolMeta } from "../lib/tools";

export type ToolStep = {
  type: "tool";
  id: string;
  name: string;
  input: Record<string, unknown>;
  output?: unknown;
  isError?: boolean;
  startedAt: number;
  finishedAt?: number;
};

export type Step =
  | { type: "connected"; tools: number }
  | { type: "text"; text: string }
  | ToolStep
  | { type: "error"; message: string }
  | { type: "stopped" };

export interface Turn {
  user: string;
  images: { url: string; preview: string; name: string }[];
  steps: Step[];
  pending: boolean;
}

export function UserMessage({ text, images }: { text: string; images: Turn["images"] }) {
  return (
    <div className="msg-user">
      {images.length > 0 && (
        <div className="user-images">
          {images.map((img) => (
            <a key={img.url} href={img.url} target="_blank" rel="noreferrer" title={img.name}>
              <img src={img.preview} alt={img.name} />
            </a>
          ))}
        </div>
      )}
      {text && <div className="bubble">{text}</div>}
    </div>
  );
}

function ToolCard({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const meta = toolMeta(step.name);
  const Icon = meta.icon;
  const running = step.finishedAt === undefined;
  const summary = !running && !step.isError ? summarizeResult(step.output) : undefined;
  const label = running ? meta.running(step.input) : meta.done(step.input);
  const image = !running && !step.isError ? resultImage(step.output) : undefined;

  return (
    <div className={`tool-card kind-${meta.kind}${step.isError ? " is-error" : ""}${open ? " open" : ""}`}>
      <button className="tool-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={`tool-icon kind-${meta.kind}`}><Icon size={14} aria-hidden /></span>
        <span className="tool-label">
          {label}
          {running && "…"}
        </span>
        {summary && <span className="tool-summary">{summary}</span>}
        <span className="tool-state">
          {running ? (
            <LoaderCircle size={14} className="spin" aria-label="Running" />
          ) : step.isError ? (
            <CircleAlert size={14} aria-label="Failed" />
          ) : (
            <Check size={14} aria-label="Done" />
          )}
          {!running && <span className="mono">{formatDuration(step.finishedAt! - step.startedAt)}</span>}
        </span>
        <ChevronRight size={14} className="chevron" aria-hidden />
      </button>
      {image && (
        <a className="tool-image" href={image} target="_blank" rel="noreferrer">
          <img src={image} alt={String(step.input.prompt ?? "Generated image")} />
        </a>
      )}
      {open && (
        <div className="tool-body">
          <div className="tool-io-label">tools/call <span className="mono">{step.name}</span> · arguments</div>
          <pre>{JSON.stringify(step.input, null, 2)}</pre>
          <div className="tool-io-label">{step.isError ? "error" : "result"}</div>
          <pre className={step.isError ? "err" : undefined}>
            {running ? "Waiting for the MCP server…" : typeof step.output === "string" ? step.output : JSON.stringify(step.output, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="icon-btn subtle"
      aria-label="Copy answer"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? <Check size={15} /> : <Copy size={15} />}
    </button>
  );
}

export function AgentTurn({ turn }: { turn: Turn }) {
  const last = turn.steps[turn.steps.length - 1];
  const answer = turn.steps.filter((s) => s.type === "text").map((s) => (s as { text: string }).text).join("\n\n");
  const thinking = turn.pending && (!last || last.type === "connected" || (last.type === "tool" && last.finishedAt !== undefined));

  return (
    <div className="msg-agent">
      <div className="agent-avatar" aria-hidden>
        <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={28} height={28} />
      </div>
      <div className="agent-body">
        {turn.steps.map((step, i) => {
          switch (step.type) {
            case "connected":
              return (
                <div key={i} className="trace-line">
                  <PlugZap size={13} aria-hidden /> Connected to MCP server · {step.tools} tools available
                </div>
              );
            case "tool":
              return <ToolCard key={step.id} step={step} />;
            case "text":
              return (
                <div key={i} className={turn.pending && step === last ? "answer streaming" : "answer"}>
                  <Markdown remarkPlugins={[remarkGfm]}>{step.text}</Markdown>
                </div>
              );
            case "error":
              return (
                <div key={i} className="alert">
                  <CircleAlert size={16} aria-hidden /> {step.message}
                </div>
              );
            case "stopped":
              return (
                <div key={i} className="trace-line">
                  <OctagonX size={13} aria-hidden /> Stopped
                </div>
              );
          }
        })}
        {thinking && (
          <div className="thinking" aria-label="Agent is working">
            <span /><span /><span />
          </div>
        )}
        {!turn.pending && answer && (
          <div className="msg-actions">
            <CopyButton text={answer} />
          </div>
        )}
      </div>
    </div>
  );
}
