import { Link } from "react-router-dom";
import type { Post, PostStatus } from "../api";
import { avatarHue, displayName, excerpt, formatDate, initials, readingTime, withoutLeadingTitle } from "../lib/format";

export function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  return (
    <span
      className="avatar"
      aria-hidden
      style={{ width: size, height: size, fontSize: size * 0.4, ["--hue" as string]: avatarHue(name) }}
    >
      {initials(name)}
    </span>
  );
}

export function StatusBadge({ status }: { status: PostStatus }) {
  return <span className={`badge badge-${status}`}>{status === "draft" ? "Draft" : "Published"}</span>;
}

export function Byline({ post, size = 32 }: { post: Post; size?: number }) {
  const date = post.status === "published" ? post.published_at ?? post.updated_at : post.updated_at;
  return (
    <div className="byline">
      <Avatar name={post.author} size={size} />
      <div>
        <div className="byline-name">{displayName(post.author)}</div>
        <div className="byline-meta">
          {post.status === "draft" ? "Edited " : ""}
          <time dateTime={date}>{formatDate(date)}</time> · {readingTime(post.content)}
        </div>
      </div>
    </div>
  );
}

export function PostCard({ post, featured = false }: { post: Post; featured?: boolean }) {
  return (
    <article className={featured ? "card card-featured" : "card"}>
      <Link to={`/posts/${post.id}`} className="card-link">
        <div className="card-top">
          {post.status === "draft" && <StatusBadge status="draft" />}
          {featured && <span className="eyebrow">Latest story</span>}
        </div>
        <h2 className="card-title">{post.title}</h2>
        <p className="card-excerpt">{excerpt(withoutLeadingTitle(post.content, post.title), featured ? 260 : 150) || "No content yet."}</p>
      </Link>
      <Byline post={post} size={featured ? 36 : 28} />
    </article>
  );
}

export function CardSkeleton({ featured = false }: { featured?: boolean }) {
  return (
    <div className={featured ? "card card-featured skeleton-card" : "card skeleton-card"} aria-hidden>
      <span className="skeleton" style={{ width: "30%", height: 12 }} />
      <span className="skeleton" style={{ width: "85%", height: featured ? 34 : 22 }} />
      <span className="skeleton" style={{ width: "100%", height: 14 }} />
      <span className="skeleton" style={{ width: "70%", height: 14 }} />
      <span className="skeleton" style={{ width: "40%", height: 28, marginTop: "auto" }} />
    </div>
  );
}
