import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, EyeOff, FileQuestion, Pencil, Send, Sparkles, Trash2 } from "lucide-react";
import { api, type Post } from "../api";
import { CHAT_URL } from "../components/Layout";
import { ConfirmDialog, EmptyState, useToast } from "../components/Feedback";
import { Byline, StatusBadge } from "../components/PostBits";
import { withoutCoverImage, withoutLeadingTitle } from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";

export function PostView() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const notify = useToast();
  const [post, setPost] = useState<Post>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  usePageTitle(post?.title);

  useEffect(() => {
    api.get(id).then(setPost).catch((e) => setError(e.message));
  }, [id]);

  async function run(action: () => Promise<Post>, success: string) {
    setBusy(true);
    try {
      setPost(await action());
      notify("success", success);
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setConfirmDelete(false);
    setBusy(true);
    try {
      await api.remove(id);
      notify("success", "Post deleted");
      navigate("/");
    } catch (e) {
      notify("error", (e as Error).message);
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div className="container section">
        <EmptyState icon={<FileQuestion size={22} />} title="Post not found">
          <p className="muted">{error}</p>
          <Link to="/" className="btn btn-secondary">Back to stories</Link>
        </EmptyState>
      </div>
    );
  }

  if (!post) {
    return (
      <div className="article-wrap" aria-busy>
        <span className="skeleton" style={{ width: 120, height: 14 }} />
        <span className="skeleton" style={{ width: "90%", height: 44, marginTop: 24 }} />
        <span className="skeleton" style={{ width: 220, height: 36, marginTop: 20 }} />
        {[100, 96, 98, 70].map((w, i) => <span key={i} className="skeleton" style={{ width: `${w}%`, height: 16, marginTop: 14 }} />)}
      </div>
    );
  }

  return (
    <article className="article-wrap">
      <Link to="/" className="back-link"><ArrowLeft size={16} aria-hidden /> All stories</Link>

      <header className="article-header">
        {post.status === "draft" && <StatusBadge status="draft" />}
        <h1 className="article-title">{post.title}</h1>
        <div className="article-meta">
          <Byline post={post} size={40} />
          <div className="toolbar" role="toolbar" aria-label="Post actions">
            <Link to={`/posts/${id}/edit`} className="btn btn-secondary btn-sm">
              <Pencil size={15} aria-hidden /> Edit
            </Link>
            {post.status === "draft" ? (
              <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => run(() => api.publish(id), "Post published")}>
                <Send size={15} aria-hidden /> Publish
              </button>
            ) : (
              <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => run(() => api.unpublish(id), "Moved back to drafts")}>
                <EyeOff size={15} aria-hidden /> Unpublish
              </button>
            )}
            <button className="btn btn-ghost-danger btn-sm" disabled={busy} onClick={() => setConfirmDelete(true)} aria-label="Delete post">
              <Trash2 size={15} aria-hidden />
            </button>
          </div>
        </div>
      </header>

      {post.cover_image_url && (
        <figure className="article-cover">
          <img src={post.cover_image_url} alt="" />
        </figure>
      )}

      <div className="prose">
        {post.content.trim() ? (
          <Markdown remarkPlugins={[remarkGfm]}>{withoutCoverImage(withoutLeadingTitle(post.content, post.title), post.cover_image_url)}</Markdown>
        ) : (
          <p className="muted">This post has no content yet.</p>
        )}
      </div>

      <aside className="ai-callout">
        <Sparkles size={20} aria-hidden />
        <div>
          <strong>Want a second opinion?</strong>
          <p>Ask the AI assistant to review this post, suggest edits, or draft a follow-up. It works on posts through MCP.</p>
        </div>
        <a href={CHAT_URL} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">Open assistant</a>
      </aside>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this post?"
        body={<p>“{post.title}” will be permanently deleted. This can’t be undone.</p>}
        confirmLabel="Delete post"
        danger
        onConfirm={remove}
        onCancel={() => setConfirmDelete(false)}
      />
    </article>
  );
}
