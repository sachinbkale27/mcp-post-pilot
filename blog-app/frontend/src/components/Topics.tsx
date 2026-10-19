import { Link } from "react-router-dom";
import { Hash, LayoutGrid } from "lucide-react";
import type { Category, PostStatus } from "../api";

/** Link to the home page with a category (or none), keeping the Published/Drafts filter. */
export function topicHref(category: string | undefined, status?: PostStatus) {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (status) params.set("status", status);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

interface Props {
  categories?: Category[];
  active?: string;
  status?: PostStatus;
  total?: number;
}

/** Left-hand Topics panel (a scrollable row of chips on small screens). */
export function TopicsPanel({ categories, active, status, total }: Props) {
  const isActive = (name?: string) => (active ?? "").toLowerCase() === (name ?? "").toLowerCase();
  return (
    <nav className="topics" aria-label="Topics">
      <h2 className="topics-title">Topics</h2>
      <ul>
        <li>
          <Link to={topicHref(undefined, status)} className={!active ? "topic active" : "topic"} aria-current={!active ? "page" : undefined}>
            <LayoutGrid size={15} aria-hidden />
            <span className="topic-name">All topics</span>
            {total !== undefined && <span className="topic-count">{total}</span>}
          </Link>
        </li>
        {categories
          ? categories.map((c) => (
              <li key={c.name}>
                <Link
                  to={topicHref(c.name, status)}
                  className={isActive(c.name) ? "topic active" : "topic"}
                  aria-current={isActive(c.name) ? "page" : undefined}
                >
                  <Hash size={15} aria-hidden />
                  <span className="topic-name">{c.name}</span>
                  <span className="topic-count">{c.count}</span>
                </Link>
              </li>
            ))
          : [70, 55, 62].map((w, i) => (
              <li key={i} className="topic-skeleton"><span className="skeleton" style={{ width: `${w}%`, height: 14 }} /></li>
            ))}
      </ul>
      {categories && categories.length === 0 && <p className="topics-empty">No topics yet. Add a category when writing a post.</p>}
    </nav>
  );
}
