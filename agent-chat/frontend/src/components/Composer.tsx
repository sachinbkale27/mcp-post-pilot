import { useEffect, useRef, type FormEvent } from "react";
import { ArrowUp, Square } from "lucide-react";

interface Props {
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
}

export function Composer({ value, busy, onChange, onSend, onStop }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow with the text, up to the CSS max-height.
  useEffect(() => {
    const el = ref.current;
    if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }
  }, [value]);

  useEffect(() => { if (!busy) ref.current?.focus(); }, [busy]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) onStop();
    else if (value.trim()) onSend();
  }

  return (
    <form className="composer" onSubmit={submit}>
      <div className="composer-box">
        <textarea
          ref={ref}
          rows={1}
          value={value}
          placeholder="Ask the agent to find, write, edit or publish posts…"
          aria-label="Message"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
          }}
        />
        <button
          type="submit"
          className={busy ? "send stop" : "send"}
          disabled={!busy && !value.trim()}
          aria-label={busy ? "Stop" : "Send"}
        >
          {busy ? <Square size={14} fill="currentColor" /> : <ArrowUp size={18} />}
        </button>
      </div>
      <p className="composer-hint">
        Enter to send · Shift+Enter for a new line · The agent can create, edit, publish and delete posts.
      </p>
    </form>
  );
}
