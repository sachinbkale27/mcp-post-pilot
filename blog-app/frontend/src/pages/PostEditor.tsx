import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, Eye, PenLine, Send } from "lucide-react";
import { api, type Category, type Post, type PostInput } from "../api";
import { ConfirmDialog, useToast } from "../components/Feedback";
import { readingTime, withoutCoverImage, withoutLeadingTitle, wordCount } from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";

const EMPTY: PostInput = { title: "", content: "", author: "", category: "" };

export function PostEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const notify = useToast();
  const [form, setForm] = useState<PostInput>(EMPTY);
  const [saved, setSaved] = useState<PostInput>(EMPTY);
  const [post, setPost] = useState<Post>();
  const [mode, setMode] = useState<"write" | "preview">("write");
  const [saving, setSaving] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);
  const titleRef = useRef<HTMLTextAreaElement>(null);
  const contentRef = useRef<HTMLTextAreaElement>(null);

  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  usePageTitle(id ? `Edit: ${form.title || "Untitled"}` : "New post");

  useEffect(() => {
    if (!id) return;
    api.get(Number(id))
      .then((p) => {
        const loaded = { title: p.title, content: p.content, author: p.author, category: p.category ?? "" };
        setPost(p);
        setForm(loaded);
        setSaved(loaded);
      })
      .catch((e) => notify("error", e.message));
  }, [id, notify]);

  useEffect(() => {
    api.categories().then(setCategories).catch(() => setCategories([]));
  }, []);

  // Grow the title and body fields with their text, like a document.
  useEffect(() => {
    for (const el of [titleRef.current, contentRef.current]) {
      if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }
    }
  }, [form.title, form.content, mode]);

  // Warn before closing the tab with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = useCallback(async (publish = false) => {
    if (!form.title.trim()) {
      notify("error", "Add a title before saving");
      titleRef.current?.focus();
      return;
    }
    setSaving(true);
    try {
      const body = { ...form, author: form.author.trim() || "anonymous" };
      let result = id ? await api.update(Number(id), body) : await api.create(body);
      if (publish) result = await api.publish(result.id);
      setSaved(form);
      notify("success", publish ? "Post published" : "Saved");
      if (publish || !id) navigate(publish ? `/posts/${result.id}` : `/posts/${result.id}/edit`, { replace: !id });
      else setPost(result);
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setSaving(false);
    }
  }, [form, id, navigate, notify]);

  // Cmd/Ctrl+S saves.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (!saving) save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, saving]);

  const leave = () => navigate(id ? `/posts/${id}` : "/");
  const set = (field: keyof PostInput) => (e: { target: { value: string } }) => setForm({ ...form, [field]: e.target.value });
  const isDraft = !post || post.status === "draft";

  return (
    <div className="editor">
      <div className="editor-bar">
        <div className="container editor-bar-inner">
          <button className="btn btn-ghost btn-sm" onClick={() => (dirty ? setConfirmLeave(true) : leave())}>
            <ArrowLeft size={16} aria-hidden /> Back
          </button>
          <span className="editor-status" aria-live="polite">
            {saving ? "Saving…" : dirty ? "Unsaved changes" : id ? "All changes saved" : "New draft"}
          </span>
          <div className="segmented" role="tablist" aria-label="Editor mode">
            <button role="tab" aria-selected={mode === "write"} className={mode === "write" ? "active" : ""} onClick={() => setMode("write")}>
              <PenLine size={14} aria-hidden /> Write
            </button>
            <button role="tab" aria-selected={mode === "preview"} className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>
              <Eye size={14} aria-hidden /> Preview
            </button>
          </div>
          <div className="editor-actions">
            <button className="btn btn-secondary btn-sm" disabled={saving || (!dirty && !!id)} onClick={() => save()} title="Save (⌘S)">
              {isDraft ? "Save draft" : "Save"}
            </button>
            {isDraft && (
              <button className="btn btn-primary btn-sm" disabled={saving} onClick={() => save(true)}>
                <Send size={15} aria-hidden /> Publish
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="editor-body">
        {mode === "write" ? (
          <>
            <textarea
              ref={titleRef}
              className="editor-title"
              placeholder="Title"
              aria-label="Title"
              rows={1}
              maxLength={200}
              value={form.title}
              onChange={set("title")}
              onKeyDown={(e) => e.key === "Enter" && e.preventDefault()}
            />
            <div className="editor-meta">
              <input className="editor-author" placeholder="Author name" aria-label="Author" value={form.author} onChange={set("author")} />
              <input
                className="editor-category"
                placeholder="Topic, e.g. Science"
                aria-label="Topic"
                list="topic-options"
                maxLength={60}
                value={form.category ?? ""}
                onChange={set("category")}
              />
              <datalist id="topic-options">
                {categories.map((c) => <option key={c.name} value={c.name} />)}
              </datalist>
            </div>
            <textarea
              ref={contentRef}
              className="editor-content"
              placeholder={"Tell your story…\n\nMarkdown works here: **bold**, _italic_, # headings, > quotes, - lists, `code`, tables."}
              aria-label="Content (Markdown)"
              value={form.content}
              onChange={set("content")}
            />
          </>
        ) : (
          <div className="preview">
            <h1 className="article-title">{form.title || "Untitled"}</h1>
            <div className="prose">
              {form.content.trim() ? <Markdown remarkPlugins={[remarkGfm]}>{withoutCoverImage(withoutLeadingTitle(form.content, form.title), post?.cover_image_url)}</Markdown> : <p className="muted">Nothing to preview yet.</p>}
            </div>
          </div>
        )}
      </div>

      <div className="editor-footer muted">
        {wordCount(form.content)} words · {readingTime(form.content)} · Markdown supported
      </div>

      <ConfirmDialog
        open={confirmLeave}
        title="Discard unsaved changes?"
        body={<p>Your latest edits haven’t been saved.</p>}
        confirmLabel="Discard changes"
        danger
        onConfirm={() => { setConfirmLeave(false); leave(); }}
        onCancel={() => setConfirmLeave(false)}
      />
    </div>
  );
}
