import type { ReactNode } from "react";
import { ChevronRight, MessageCircleQuestion } from "lucide-react";

export type FaqItem = { q: string; a: ReactNode };

/** Tags for answers that list a form's fields. */
export const Need = () => <span className="faq-tag need">Required</span>;
export const Optional = () => <span className="faq-tag">Optional</span>;

/** A collapsed list of short questions at the top of a page; each opens to a plain answer. */
export function Faq({ title, items }: { title: string; items: FaqItem[] }) {
  return (
    <details className="page-faq">
      <summary>
        <MessageCircleQuestion size={16} aria-hidden /> {title}
        <span>{items.length} short answers</span>
        <ChevronRight size={15} className="chevron" aria-hidden />
      </summary>
      <div className="faq-list">
        {items.map(({ q, a }) => (
          <details key={q} className="faq-item">
            <summary><ChevronRight size={14} className="chevron" aria-hidden /> {q}</summary>
            <div className="faq-answer">{a}</div>
          </details>
        ))}
      </div>
    </details>
  );
}
