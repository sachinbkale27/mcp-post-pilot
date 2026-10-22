import { BookText, Bot, FileCode2, MessageSquarePlus, Network, PanelLeftClose, SquareArrowOutUpRight } from "lucide-react";
import { BLOG_URL, type AgentInfo, type AgentsInfo } from "../api";
import { toolMeta } from "../lib/tools";

interface Props {
  info?: AgentsInfo;
  infoError?: string;
  busy: boolean;
  open: boolean;
  onNewChat: () => void;
  onRetry: () => void;
  onClose: () => void;
}

export function Brand() {
  return (
    <div className="brand">
      <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={30} height={30} />
      <div>
        <div className="brand-name">Post Pilot <span>Agent</span></div>
        <div className="brand-sub">Multi-agent · MCP · LangGraph</div>
      </div>
    </div>
  );
}

function host(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function AgentPanel({ agent, defaultOpen }: { agent: AgentInfo; defaultOpen: boolean }) {
  const tools = agent.tools ?? [];
  const extras = [...(agent.resources ?? []), ...(agent.resource_templates ?? [])];
  return (
    <details className="agent-panel" open={defaultOpen}>
      <summary>
        <span className="agent-icon"><Bot size={14} aria-hidden /></span>
        <span className="agent-panel-title">{agent.title}</span>
        <span className={`status status-${agent.online ? "online" : "offline"}`}>
          <span className="status-dot" /> {agent.online ? `${tools.length} tools` : "Offline"}
        </span>
      </summary>
      <p className="agent-desc">{agent.description}</p>
      <dl className="facts">
        <div><dt>MCP server</dt><dd className="mono" title={agent.server_url}>{host(agent.server_url)}</dd></div>
      </dl>
      {agent.error && <p className="panel-error">{agent.error}</p>}
      {tools.length > 0 && (
        <ul className="tool-list">
          {tools.map((tool) => {
            const meta = toolMeta(tool.name);
            const Icon = meta.icon;
            return (
              <li key={tool.name} title={tool.description ?? undefined}>
                <span className={`tool-icon kind-${meta.kind}`}><Icon size={14} aria-hidden /></span>
                <span className="tool-name">{tool.name}</span>
                <span className={`kind-tag kind-${meta.kind}`}>{meta.kind}</span>
              </li>
            );
          })}
        </ul>
      )}
      {(extras.length > 0 || (agent.prompts ?? []).length > 0) && (
        <div className="chips">
          {extras.map((r) => (
            <span key={r} className="chip mono"><FileCode2 size={12} aria-hidden /> {r}</span>
          ))}
          {(agent.prompts ?? []).map((p) => (
            <span key={p.name} className="chip mono" title={p.description ?? undefined}>{p.name}</span>
          ))}
        </div>
      )}
    </details>
  );
}

export function Sidebar({ info, infoError, busy, open, onNewChat, onRetry, onClose }: Props) {
  const online = info?.agents.filter((a) => a.online).length ?? 0;
  const status = infoError ? "offline" : info ? (online === info.agents.length ? "online" : "partial") : "connecting";

  return (
    <aside className={open ? "sidebar open" : "sidebar"} aria-label="Agents and MCP servers">
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
          <Network size={14} aria-hidden /> Supervisor
          <span className={`status status-${status === "partial" ? "offline" : status}`}>
            <span className="status-dot" />{" "}
            {status === "online" ? "Ready" : status === "partial" ? `${online}/${info!.agents.length} agents` : status === "offline" ? "Offline" : "Connecting"}
          </span>
        </div>
        {infoError && (
          <p className="panel-error">
            {infoError} · <button className="link-btn" onClick={onRetry}>Retry</button>
          </p>
        )}
        {info && (
          <dl className="facts">
            <div><dt>Model</dt><dd className="mono">{info.model}</dd></div>
            <div><dt>Agents</dt><dd>{info.agents.length}</dd></div>
            <div><dt>Transport</dt><dd>Streamable HTTP</dd></div>
          </dl>
        )}
      </section>

      <section className="panel panel-grow">
        <div className="panel-head">
          Agents <span className="count">{info?.agents.length ?? "–"}</span>
        </div>
        <div className="agent-panels">
          {info
            ? info.agents.map((agent, i) => <AgentPanel key={agent.name} agent={agent} defaultOpen={i === 0} />)
            : Array.from({ length: 2 }, (_, i) => <div key={i} className="skeleton" style={{ height: 34 }} />)}
        </div>
      </section>

      <a className="sidebar-link" href={BLOG_URL} target="_blank" rel="noreferrer">
        <BookText size={16} aria-hidden /> Open the blog <SquareArrowOutUpRight size={13} aria-hidden />
      </a>
    </aside>
  );
}
