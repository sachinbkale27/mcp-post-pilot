/** Formatting helpers shared by the pages. */

const WORDS_PER_MINUTE = 220;

/** Plain-text preview of a Markdown body. */
export function excerpt(markdown: string, maxLength = 180): string {
  const text = markdown
    .replace(/```[\s\S]*?```/g, " ")         // code blocks
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")    // images
    .replace(/\[([^\]]*)]\([^)]*\)/g, "$1")   // links -> text
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "") // headings, quotes, list markers
    .replace(/[*_`~]/g, "")                   // emphasis and inline code
    .replace(/\s+/g, " ")
    .trim();
  if (text.length <= maxLength) return text;
  return text.slice(0, text.lastIndexOf(" ", maxLength) > 0 ? text.lastIndexOf(" ", maxLength) : maxLength) + "…";
}

export function wordCount(markdown: string): number {
  return markdown.trim() ? markdown.trim().split(/\s+/).length : 0;
}

export function readingTime(markdown: string): string {
  return `${Math.max(1, Math.round(wordCount(markdown) / WORDS_PER_MINUTE))} min read`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function displayName(author: string): string {
  const name = author.trim() || "anonymous";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export function initials(author: string): string {
  const parts = displayName(author).split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

const AVATAR_HUES = [228, 262, 190, 152, 28, 340, 205, 290];

/** A stable hue per author, so each author keeps the same avatar color. */
export function avatarHue(author: string): number {
  let hash = 0;
  for (const ch of author.toLowerCase()) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_HUES[hash % AVATAR_HUES.length];
}

/**
 * Drop a first line that only repeats the title (agent-written posts often start with
 * "**Title**" or "# Title"), so cards and articles don't show the title twice.
 */
export function withoutLeadingTitle(markdown: string, title: string): string {
  const lines = markdown.split("\n");
  const first = lines.findIndex((line) => line.trim() !== "");
  if (first === -1) return markdown;
  const plain = lines[first].replace(/^\s*#{1,6}\s+/, "").replace(/[*_`]/g, "").trim().toLowerCase();
  return plain === title.trim().toLowerCase() ? lines.slice(first + 1).join("\n").trimStart() : markdown;
}
