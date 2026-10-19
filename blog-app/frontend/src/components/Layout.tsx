import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { PenLine, Search, Sparkles } from "lucide-react";

const CHAT_URL = import.meta.env.VITE_CHAT_URL ?? "http://localhost:5174";

export function Logo() {
  return (
    <Link to="/" className="logo" aria-label="Post Pilot home">
      <img src="/favicon.svg" alt="" width={28} height={28} />
      <span>Post Pilot</span>
    </Link>
  );
}

/** "Stories" and "Drafts" share the "/" path, so the active link depends on ?status. */
function MainNav() {
  const { pathname, search } = useLocation();
  const onHome = pathname === "/";
  const drafts = onHome && new URLSearchParams(search).get("status") === "draft";
  return (
    <nav className="main-nav" aria-label="Main">
      <Link to="/" className={onHome && !drafts ? "active" : undefined} aria-current={onHome && !drafts ? "page" : undefined}>
        Stories
      </Link>
      <Link to="/?status=draft" className={drafts ? "active" : undefined} aria-current={drafts ? "page" : undefined}>
        Drafts
      </Link>
    </nav>
  );
}

function SearchBox() {
  const [params] = useSearchParams();
  const [value, setValue] = useState(params.get("q") ?? "");
  const navigate = useNavigate();

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = value.trim();
    navigate(q ? `/?q=${encodeURIComponent(q)}` : "/");
  }

  return (
    <form className="search" role="search" onSubmit={submit}>
      <Search size={16} aria-hidden />
      <input
        type="search"
        placeholder="Search posts"
        aria-label="Search posts"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    </form>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <header className="site-header">
        <div className="container header-inner">
          <Logo />
          <MainNav />
          <div className="header-actions">
            <SearchBox />
            <a className="btn btn-ghost" href={CHAT_URL} target="_blank" rel="noreferrer">
              <Sparkles size={16} aria-hidden /> <span className="hide-sm">Ask AI</span>
            </a>
            <Link className="btn btn-primary" to="/new">
              <PenLine size={16} aria-hidden /> <span className="hide-sm">Write</span>
            </Link>
          </div>
        </div>
      </header>
      <main className="site-main">{children}</main>
      <footer className="site-footer">
        <div className="container footer-inner">
          <Logo />
          <p>
            Posts here can be written by people or by an AI agent through the{" "}
            <a href="https://modelcontextprotocol.io" target="_blank" rel="noreferrer">Model Context Protocol</a>.
          </p>
          <nav className="footer-links" aria-label="Footer">
            <a href={CHAT_URL} target="_blank" rel="noreferrer">AI assistant</a>
            <a href="https://github.com/sachinbkale27/mcp-post-pilot" target="_blank" rel="noreferrer">Source</a>
            <a href="https://sachin-kale.com" target="_blank" rel="noreferrer">sachin-kale.com</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}

export { CHAT_URL };
