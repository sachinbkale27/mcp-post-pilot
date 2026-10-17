import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type PostInput } from "../api";

const EMPTY: PostInput = { title: "", content: "", author: "" };

export function PostEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState<PostInput>(EMPTY);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!id) return;
    api
      .get(Number(id))
      .then(({ title, content, author }) => setForm({ title, content, author }))
      .catch((e) => setError(e.message));
  }, [id]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const body = { ...form, author: form.author || "anonymous" };
      const post = id ? await api.update(Number(id), body) : await api.create(body);
      navigate(`/posts/${post.id}`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const set = (field: keyof PostInput) => (e: { target: { value: string } }) =>
    setForm({ ...form, [field]: e.target.value });

  return (
    <form className="editor" onSubmit={submit}>
      <h1>{id ? "Edit post" : "New post"}</h1>
      {error && <p className="error">{error}</p>}
      <label>
        Title
        <input value={form.title} onChange={set("title")} required maxLength={200} />
      </label>
      <label>
        Author
        <input value={form.author} onChange={set("author")} placeholder="anonymous" />
      </label>
      <label>
        Content (Markdown)
        <textarea value={form.content} onChange={set("content")} rows={16} />
      </label>
      <div className="actions">
        <button type="submit">{id ? "Save changes" : "Save draft"}</button>
        <button type="button" className="secondary" onClick={() => navigate(-1)}>Cancel</button>
      </div>
    </form>
  );
}
