const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8100";

export type PostStatus = "draft" | "published";

export interface Post {
  id: number;
  title: string;
  content: string;
  author: string;
  status: PostStatus;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  cover_image_url?: string | null;
}

export type PostInput = Pick<Post, "title" | "content" | "author">;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  list: (filters: { status?: PostStatus; q?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.q) params.set("q", filters.q);
    const query = params.toString();
    return request<Post[]>(`/posts${query ? `?${query}` : ""}`);
  },
  get: (id: number) => request<Post>(`/posts/${id}`),
  create: (body: PostInput) => request<Post>("/posts", { method: "POST", body: JSON.stringify(body) }),
  update: (id: number, body: Partial<PostInput>) =>
    request<Post>(`/posts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  publish: (id: number) => request<Post>(`/posts/${id}/publish`, { method: "POST" }),
  unpublish: (id: number) => request<Post>(`/posts/${id}/unpublish`, { method: "POST" }),
  remove: (id: number) => request<void>(`/posts/${id}`, { method: "DELETE" }),
};
