import { useEffect, useRef, useState } from "react";
import type { ChatStatus, UiMessage } from "../hooks/useChatStream";
import SourceCard from "./SourceCard";

interface MessageListProps {
  messages: UiMessage[];
  status: ChatStatus;
}

const CITATION_SPLIT = /(\[\d+\])/g;
const CITATION_EXACT = /^\[(\d+)\]$/;

export default function MessageList({ messages, status }: MessageListProps) {
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, status]);

  function jumpToSource(anchorId: string) {
    const element = document.getElementById(anchorId);
    if (element === null) return;
    element.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setHighlighted(anchorId);
    window.setTimeout(() => {
      setHighlighted((current) => (current === anchorId ? null : current));
    }, 1500);
  }

  /** Split assistant text on [n] markers; valid ones become anchor buttons. */
  function renderAssistantText(content: string, messageIndex: number, sourceCount: number) {
    return content.split(CITATION_SPLIT).map((part, i) => {
      const match = CITATION_EXACT.exec(part);
      if (match !== null) {
        const n = Number(match[1]);
        if (n >= 1 && n <= sourceCount) {
          const anchorId = `source-${messageIndex}-${n}`;
          return (
            <button
              key={i}
              type="button"
              onClick={() => jumpToSource(anchorId)}
              className="mx-0.5 rounded bg-indigo-950 px-1 font-mono text-xs text-indigo-300 hover:bg-indigo-900"
            >
              [{n}]
            </button>
          );
        }
      }
      return <span key={i}>{part}</span>;
    });
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4">
      {messages.length === 0 && (
        <div className="flex h-full items-center justify-center text-sm text-neutral-500">
          Ask a question. Answers cite their sources.
        </div>
      )}
      <ul className="mx-auto flex max-w-3xl flex-col gap-4">
        {messages.map((message, messageIndex) => (
          <li key={messageIndex} className={message.role === "user" ? "self-end" : "w-full"}>
            {message.role === "user" ? (
              <div className="whitespace-pre-wrap rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white">
                {message.content}
              </div>
            ) : (
              <div className="w-full">
                <div className="whitespace-pre-wrap rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3 text-sm leading-relaxed">
                  {message.content === "" && status === "retrieving" ? (
                    <span className="text-neutral-500">Searching the knowledge base…</span>
                  ) : (
                    renderAssistantText(message.content, messageIndex, message.sources?.length ?? 0)
                  )}
                </div>
                {message.sources !== undefined && message.sources.length > 0 && (
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    {message.sources.map((source, i) => (
                      <SourceCard
                        key={source.chunk_id}
                        source={source}
                        index={i + 1}
                        anchorId={`source-${messageIndex}-${i + 1}`}
                        highlighted={highlighted === `source-${messageIndex}-${i + 1}`}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div ref={bottomRef} />
    </div>
  );
}
