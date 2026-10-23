import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent } from "react";
import { ArrowUp, CircleAlert, ImagePlus, LoaderCircle, Square, X } from "lucide-react";
import { ACCEPTED_TYPES } from "../lib/images";

export const MAX_ATTACHMENTS = 4;

export interface Attachment {
  id: string;
  name: string;
  status: "processing" | "uploading" | "ready" | "error";
  preview?: string;  // resized data URL, also sent to the model
  url?: string;      // public /media/... URL once uploaded
  error?: string;
}

interface Props {
  value: string;
  focusSignal?: number; // changes when the app puts a question in the box for the user to finish
  busy: boolean;
  attachments: Attachment[];
  onChange: (value: string) => void;
  onAddFiles: (files: File[]) => void;
  onRemoveAttachment: (id: string) => void;
  onSend: () => void;
  onStop: () => void;
}

export function Composer({ value, focusSignal, busy, attachments, onChange, onAddFiles, onRemoveAttachment, onSend, onStop }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const uploading = attachments.some((a) => a.status === "processing" || a.status === "uploading");
  const ready = attachments.some((a) => a.status === "ready");
  const canSend = !uploading && (value.trim() !== "" || ready);
  const full = attachments.length >= MAX_ATTACHMENTS;

  // Grow with the text, up to the CSS max-height.
  useEffect(() => {
    const el = ref.current;
    if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }
  }, [value]);

  useEffect(() => { if (!busy) ref.current?.focus(); }, [busy]);

  // Focus with the cursor at the end, ready to type the rest
  useEffect(() => {
    const el = ref.current;
    if (el && focusSignal) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
  }, [focusSignal]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) onStop();
    else if (canSend) onSend();
  }

  function addFrom(list: FileList | null | undefined) {
    const files = Array.from(list ?? []).filter((f) => f.type.startsWith("image/"));
    if (files.length) onAddFiles(files);
  }

  function onPaste(e: ClipboardEvent) {
    if (e.clipboardData.files.length) {
      e.preventDefault();
      addFrom(e.clipboardData.files);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    addFrom(e.dataTransfer.files);
  }

  return (
    <form className="composer" onSubmit={submit}>
      <div
        className={dragging ? "composer-box dragging" : "composer-box"}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {attachments.length > 0 && (
          <div className="attachments">
            {attachments.map((a) => (
              <div key={a.id} className={`attachment status-${a.status}`} title={a.error ?? a.name}>
                {a.preview ? <img src={a.preview} alt={a.name} /> : <div className="attachment-blank" />}
                {(a.status === "processing" || a.status === "uploading") && (
                  <span className="attachment-overlay"><LoaderCircle size={18} className="spin" aria-label="Uploading" /></span>
                )}
                {a.status === "error" && (
                  <span className="attachment-overlay error"><CircleAlert size={18} aria-label={a.error} /></span>
                )}
                <button type="button" className="attachment-remove" onClick={() => onRemoveAttachment(a.id)} aria-label={`Remove ${a.name}`}>
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="composer-row">
          <button
            type="button"
            className="attach"
            onClick={() => fileRef.current?.click()}
            disabled={busy || full}
            aria-label="Attach images"
            title={full ? `Up to ${MAX_ATTACHMENTS} images` : "Attach images"}
          >
            <ImagePlus size={19} />
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPTED_TYPES.join(",")}
            multiple
            hidden
            onChange={(e) => { addFrom(e.target.files); e.target.value = ""; }}
          />
          <textarea
            ref={ref}
            rows={1}
            value={value}
            placeholder={attachments.length ? "Tell the agent what to do with these images…" : "Ask the agent to find, write, edit or publish posts…"}
            aria-label="Message"
            onChange={(e) => onChange(e.target.value)}
            onPaste={onPaste}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
            }}
          />
          <button
            type="submit"
            className={busy ? "send stop" : "send"}
            disabled={!busy && !canSend}
            aria-label={busy ? "Stop" : "Send"}
          >
            {busy ? <Square size={14} fill="currentColor" /> : <ArrowUp size={18} />}
          </button>
        </div>
        {dragging && <div className="drop-hint">Drop images to attach</div>}
      </div>
      <p className="composer-hint">
        Enter to send · Shift+Enter for a new line · Attach, paste or drop up to {MAX_ATTACHMENTS} images · The agent can create, edit, publish and delete posts.
      </p>
    </form>
  );
}
