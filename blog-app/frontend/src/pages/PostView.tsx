import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Markdown from "react-markdown";
import { api, type Post } from "../api";

export function PostView() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [post, setPost] = useState<Post>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    api.get(id).then(setPost).catch((e) => setError(e.message));
  }, [id]);

  async function run(action: () => Promise<Post>) {
    try {
      setPost(await action());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove() {
    if (!confirm("Delete this post permanently?")) return;
    await api.remove(id).catch((e) => setError(e.message));
    navigate("/");
  }

  if (error) return <p className="error">{error}</p>;
  if (!post) return <p className="muted">Loading…</p>;

  return (
    <article>
      <h1>{post.title}</h1>
      <p className="muted">
        by {post.author} · <span className={`badge ${post.status}`}>{post.status}</span>
        {post.published_at && <> · published {new Date(post.published_at).toLocaleString()}</>}
      </p>
      <div className="actions">
        <Link className="button secondary" to={`/posts/${id}/edit`}>Edit</Link>
        {post.status === "draft" ? (
          <button onClick={() => run(() => api.publish(id))}>Publish</button>
        ) : (
          <button className="secondary" onClick={() => run(() => api.unpublish(id))}>Unpublish</button>
        )}
        <button className="danger" onClick={remove}>Delete</button>
      </div>
      <div className="content">
        <Markdown>{post.content}</Markdown>
      </div>
    </article>
  );
}
