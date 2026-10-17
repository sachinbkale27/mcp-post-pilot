import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Post, type PostStatus } from "../api";

const FILTERS: { label: string; value?: PostStatus }[] = [
  { label: "All" },
  { label: "Drafts", value: "draft" },
  { label: "Published", value: "published" },
];

export function PostList() {
  const [filter, setFilter] = useState<PostStatus | undefined>();
  const [posts, setPosts] = useState<Post[]>([]);
  const [error, setError] = useState<string>();

  useEffect(() => {
    api.list(filter).then(setPosts).catch((e) => setError(e.message));
  }, [filter]);

  return (
    <>
      <div className="tabs">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            className={filter === f.value ? "tab active" : "tab"}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {posts.length === 0 && !error && <p className="muted">No posts yet.</p>}
      <ul className="post-list">
        {posts.map((p) => (
          <li key={p.id}>
            <Link to={`/posts/${p.id}`}>{p.title}</Link>
            <span className={`badge ${p.status}`}>{p.status}</span>
            <div className="muted small">
              #{p.id} · {p.author} · updated {new Date(p.updated_at).toLocaleString()}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
