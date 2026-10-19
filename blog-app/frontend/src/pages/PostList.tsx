import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FileText, PenLine, RefreshCw, SearchX, Sparkles } from "lucide-react";
import { api, type Post, type PostStatus } from "../api";
import { CHAT_URL } from "../components/Layout";
import { EmptyState } from "../components/Feedback";
import { CardSkeleton, PostCard } from "../components/PostBits";
import { usePageTitle } from "../lib/usePageTitle";

const TABS: { label: string; status?: PostStatus }[] = [
  { label: "All" },
  { label: "Published", status: "published" },
  { label: "Drafts", status: "draft" },
];

export function PostList() {
  const [params] = useSearchParams();
  const status = (params.get("status") as PostStatus | null) ?? undefined;
  const q = params.get("q") ?? "";
  const [posts, setPosts] = useState<Post[]>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);

  usePageTitle(q ? `Search: ${q}` : status === "draft" ? "Drafts" : undefined);

  useEffect(() => {
    setPosts(undefined);
    setError(undefined);
    api.list({ status, q: q || undefined }).then(setPosts).catch((e) => setError(e.message));
  }, [status, q, attempt]);

  const showHero = !q && !status;
  // Feature the most recent published story on the main page.
  const featured = showHero ? posts?.find((p) => p.status === "published") : undefined;
  const rest = posts?.filter((p) => p !== featured) ?? [];

  return (
    <>
      {showHero && (
        <section className="hero">
          <div className="container">
            <span className="hero-chip">
              <Sparkles size={14} aria-hidden /> AI-assisted publishing over MCP
            </span>
            <h1>Ideas worth publishing.</h1>
            <p>
              Stories and notes written by people, drafted and edited with an AI co-pilot that manages
              posts through the Model Context Protocol.
            </p>
            <div className="hero-actions">
              <Link to="/new" className="btn btn-primary">
                <PenLine size={16} aria-hidden /> Start writing
              </Link>
              <a href={CHAT_URL} target="_blank" rel="noreferrer" className="btn btn-secondary">
                <Sparkles size={16} aria-hidden /> Draft with AI
              </a>
            </div>
          </div>
        </section>
      )}

      <section className="container section">
        {q ? (
          <div className="section-head">
            <h1 className="section-title">Results for “{q}”</h1>
            {posts && <span className="muted">{posts.length} {posts.length === 1 ? "post" : "posts"}</span>}
            <Link to="/" className="link-quiet">Clear search</Link>
          </div>
        ) : (
          <div className="section-head">
            <h2 className="section-title">{status === "draft" ? "Drafts" : "Latest stories"}</h2>
            <div className="tabs" role="tablist" aria-label="Filter posts">
              {TABS.map((tab) => (
                <Link
                  key={tab.label}
                  role="tab"
                  aria-selected={status === tab.status}
                  className={status === tab.status ? "tab active" : "tab"}
                  to={tab.status ? `/?status=${tab.status}` : "/"}
                >
                  {tab.label}
                </Link>
              ))}
            </div>
          </div>
        )}

        {error ? (
          <EmptyState icon={<RefreshCw size={22} />} title="Couldn’t load posts">
            <p className="muted">{error}</p>
            <button className="btn btn-secondary" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
          </EmptyState>
        ) : !posts ? (
          <>
            {showHero && <CardSkeleton featured />}
            <div className="grid">{[0, 1, 2].map((i) => <CardSkeleton key={i} />)}</div>
          </>
        ) : posts.length === 0 ? (
          q ? (
            <EmptyState icon={<SearchX size={22} />} title="No matching posts">
              <p className="muted">Try a different word, or browse all stories.</p>
              <Link to="/" className="btn btn-secondary">All stories</Link>
            </EmptyState>
          ) : (
            <EmptyState icon={<FileText size={22} />} title={status === "draft" ? "No drafts" : "Nothing here yet"}>
              <p className="muted">Write the first post yourself, or ask the AI assistant to draft one.</p>
              <Link to="/new" className="btn btn-primary"><PenLine size={16} aria-hidden /> Write a post</Link>
            </EmptyState>
          )
        ) : (
          <>
            {featured && <PostCard post={featured} featured />}
            {rest.length > 0 && <div className="grid">{rest.map((p) => <PostCard key={p.id} post={p} />)}</div>}
          </>
        )}
      </section>
    </>
  );
}
