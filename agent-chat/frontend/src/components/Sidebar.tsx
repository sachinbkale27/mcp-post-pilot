import { BookText, FileCode2, MessageSquarePlus, PanelLeftClose, Server, SquareArrowOutUpRight } from "lucide-react";
import { BLOG_URL, type McpInfo } from "../api";
import { toolMeta } from "../lib/tools";

interface Props {
  info?: McpInfo;
  infoError?: string;
  busy: boolean;
  open: boolean;
  onNewChat: () => void;
  onClose: () => void;
}

export function Brand() {
  return (
    <div className="brand">
      <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={30} height={30} />
      <div>
        <div className="brand-name">Post Pilot <span>Agent</span></div>
        <div className="brand-sub">MCP · LangGraph</div>
      </div>
    </div>
  );
}

export function Sidebar({ info, infoError, busy, open, onNewChat, onClose }: Props) {
  const status = infoError ? "offline" : info ? "online" : "connecting";

  return (
    <aside className={open ? "sidebar open" : "sidebar"} aria-label="Agent and MCP server">
      <div className="sidebar-top">
        <Brand />
        <button className="icon-btn only-mobile" onClick={onClose} aria-label="Close panel">
          <PanelLeftClose size={18} />
        </button>
      </div>

      <button className="new-chat" onClick={onNewChat} disabled={busy}>
        <MessageSquarePlus size={17} aria-hidden /> New conversation
      </button>

      <section className="panel">
        <div className="panel-head">
          <Server size={14} aria-hidden /> MCP server
          <span className={`status status-${status}`}>
            <span className="status-dot" /> {status === "online" ? "Connected" : status === "offline" ? "Offline" : "Connecting"}
          </span>
        </div>
        {infoError && <p className="panel-error">{infoError}</p>}
        {info && (
          <dl className="facts">
            <div><dt>Server</dt><dd>blog</dd></div>
            <div><dt>Model</dt><dd className="mono">{info.model}</dd></div>
            <div><dt>Transport</dt><dd>Streamable HTTP</dd></div>
          </dl>
        )}
      </section>

      <section className="panel panel-grow">
        <div className="panel-head">
          Tools <span className="count">{info?.tools.length ?? "–"}</span>
        </div>
        <ul className="tool-list">
          {info
            ? info.tools.map((tool) => {
                const meta = toolMeta(tool.name);
                const Icon = meta.icon;
                return (
                  <li key={tool.name} title={tool.description ?? undefined}>
                    <span className={`tool-icon kind-${meta.kind}`}><Icon size={14} aria-hidden /></span>
                    <span className="tool-name">{tool.name}</span>
                    <span className={`kind-tag kind-${meta.kind}`}>{meta.kind}</span>
                  </li>
                );
              })
            : Array.from({ length: 6 }, (_, i) => <li key={i}><span className="skeleton" style={{ width: `${55 + (i % 3) * 12}%` }} /></li>)}
        </ul>

        {info && (
          <>
            <div className="panel-head sub">Resources</div>
            <div className="chips">
              {[...info.resources, ...info.resource_templates].map((r) => (
                <span key={r} className="chip mono"><FileCode2 size={12} aria-hidden /> {r}</span>
              ))}
            </div>
            <div className="panel-head sub">Prompts</div>
            <div className="chips">
              {info.prompts.map((p) => (
                <span key={p.name} className="chip mono" title={p.description ?? undefined}>{p.name}</span>
              ))}
            </div>
          </>
        )}
      </section>

      <a className="sidebar-link" href={BLOG_URL} target="_blank" rel="noreferrer">
        <BookText size={16} aria-hidden /> Open the blog <SquareArrowOutUpRight size={13} aria-hidden />
      </a>
    </aside>
  );
}
