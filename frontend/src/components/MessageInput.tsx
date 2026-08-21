import { useState, type KeyboardEvent } from "react";

interface MessageInputProps {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

export default function MessageInput({ busy, onSend, onStop }: MessageInputProps) {
  const [text, setText] = useState("");

  function submit() {
    const trimmed = text.trim();
    if (trimmed === "" || busy) return;
    onSend(trimmed);
    setText("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault(); // Enter sends; Shift+Enter inserts a newline
      submit();
    }
  }

  return (
    <div>
      <div className="flex items-end gap-2.5">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={busy}
          rows={1}
          placeholder="Posez une question sur les documents indexés…"
          className="max-h-40 flex-1 resize-none rounded-[22px] bg-surface px-[18px] py-[11px] text-sm text-ink field-sizing-content placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
        />
        <button
          type="button"
          onClick={submit}
          disabled={busy || text.trim() === ""}
          aria-label="Envoyer"
          className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-white hover:bg-accent-hover disabled:opacity-40"
        >
          <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">
            <path
              d="M6.5 11V2M2.5 6 6.5 2l4 4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
      <div className="mt-2 flex justify-between px-1.5 text-[11px] text-muted">
        <span>⏎ envoyer · ⇧⏎ nouvelle ligne · questions en FR, DE, EN</span>
        {busy && (
          <button type="button" onClick={onStop} className="text-link hover:underline">
            ■ arrêter
          </button>
        )}
      </div>
    </div>
  );
}
