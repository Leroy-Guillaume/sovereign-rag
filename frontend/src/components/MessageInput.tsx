import { useState, type KeyboardEvent } from "react";

interface MessageInputProps {
  disabled: boolean;
  onSend: (text: string) => void;
}

export default function MessageInput({ disabled, onSend }: MessageInputProps) {
  const [text, setText] = useState("");

  function submit() {
    const trimmed = text.trim();
    if (trimmed === "" || disabled) return;
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
    <div className="flex flex-1 items-end gap-2">
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={2}
        placeholder="Ask about the ingested documents… (Enter to send, Shift+Enter for a new line)"
        className="flex-1 resize-none rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 placeholder:text-neutral-600 focus:border-indigo-500 focus:outline-none disabled:opacity-50"
      />
      <button
        type="button"
        onClick={submit}
        disabled={disabled || text.trim() === ""}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
      >
        Send
      </button>
    </div>
  );
}
