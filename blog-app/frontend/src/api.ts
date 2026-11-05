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
  category?: string | null;
  // Whether the current title and text passed the Fact-check agent (needed to publish), and its report
  fact_checked?: boolean;
  fact_check_at?: string | null;
  fact_check_report?: string | null;
}

export interface Category {
  name: string;
  count: number;
}

export type PostInput = Pick<Post, "title" | "content" | "author"> & { category?: string | null };

const OWNER_KEY = "blogOwnerKey";

/** The blog owner's key, kept for this browser tab only; it lets the owner change published posts. */
export function ownerKey(): string {
  try {
    return sessionStorage.getItem(OWNER_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setOwnerKey(key: string) {
  try {
    if (key) sessionStorage.setItem(OWNER_KEY, key);
    else sessionStorage.removeItem(OWNER_KEY);
  } catch { /* storage blocked: the key works for no request */ }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const key = ownerKey();
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(key ? { "x-owner-key": key } : {}) },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  list: (filters: { status?: PostStatus; q?: string; category?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.q) params.set("q", filters.q);
    if (filters.category) params.set("category", filters.category);
    const query = params.toString();
    return request<Post[]>(`/posts${query ? `?${query}` : ""}`);
  },
  categories: (status?: PostStatus) => request<Category[]>(`/categories${status ? `?status=${status}` : ""}`),
  get: (id: number) => request<Post>(`/posts/${id}`),
  create: (body: PostInput) => request<Post>("/posts", { method: "POST", body: JSON.stringify(body) }),
  update: (id: number, body: Partial<PostInput>) =>
    request<Post>(`/posts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  publish: (id: number) => request<Post>(`/posts/${id}/publish`, { method: "POST" }),
  unpublish: (id: number) => request<Post>(`/posts/${id}/unpublish`, { method: "POST" }),
  remove: (id: number) => request<void>(`/posts/${id}`, { method: "DELETE" }),
};
