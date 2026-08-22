import { useEffect, useRef, useState } from "react";
import type { ChatStatus, UiMessage } from "../hooks/useChatStream";
import { APP_COPY } from "../lib/appCopy";
import { auditLabel, formatAnswerSeconds } from "../lib/format";
import { useLang } from "../lib/lang";

export interface SourcePanelState {
  /** Index in the messages array of the assistant message whose sources are open. */
  messageIndex: number;
  /** 1-based citation number highlighted in the panel, if opened via a marker. */
  activeSource: number | null;
}

interface MessageListProps {
  messages: UiMessage[];
  status: ChatStatus;
  panel: SourcePanelState | null;
  onToggleSources: (messageIndex: number) => void;
  onOpenSource: (messageIndex: number, source: number) => void;
}

const CITATION_SPLIT = /(\[\d+\])/g;
const CITATION_EXACT = /^\[(\d+)\]$/;

export default function MessageList({
  messages,
  status,
  panel,
  onToggleSources,
  onOpenSource,
}: MessageListProps) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const { lang } = useLang();
  const t = APP_COPY[lang].chat;
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);
  const busy = status === "retrieving" || status === "streaming";

  useEffect(() => {
    // Follow the stream only while the reader is already at the bottom:
    // unconditional scrolling would yank the view back down on every delta
    // and make re-reading an earlier answer impossible mid-stream. Measured
    // on the overflow-y-auto element itself; an inner wrapper never scrolls.
    const scroller = scrollerRef.current;
    if (scroller !== null) {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      pinnedToBottom.current = distance < 80;
    }
    if (pinnedToBottom.current) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, status]);

  function copyAnswer(content: string, messageIndex: number) {
    // navigator.clipboard needs a secure context; a docker compose demo on a
    // LAN host is plain http, so fall back to the selection-based API there.
    const write =
      navigator.clipboard !== undefined
        ? navigator.clipboard.writeText(content)
        : new Promise<void>((resolve, reject) => {
            const holder = document.createElement("textarea");
            holder.value = content;
            document.body.appendChild(holder);
            holder.select();
            const copied = document.execCommand("copy");
            holder.remove();
            if (copied) resolve();
            else reject(new Error("copy rejected"));
          });
    write
      .then(() => {
        setCopiedIndex(messageIndex);
        window.setTimeout(() => {
          setCopiedIndex((current) => (current === messageIndex ? null : current));
        }, 1500);
      })
      .catch(() => {
        // Copy denied by the browser: leave the label as is, nothing to say.
      });
  }

  /** Split assistant text on [n] markers; valid ones become chips that open the panel. */
  function renderAssistantText(content: string, messageIndex: number, sourceCount: number) {
    return content.split(CITATION_SPLIT).map((part, i) => {
      const match = CITATION_EXACT.exec(part);
      if (match !== null) {
        const n = Number(match[1]);
        if (n >= 1 && n <= sourceCount) {
          const active =
            panel !== null && panel.messageIndex === messageIndex && panel.activeSource === n;
          return (
            <button
              key={i}
              type="button"
              onClick={() => onOpenSource(messageIndex, n)}
              aria-label={t.openSource(n)}
              className={`mx-[3px] inline-block -translate-y-[2px] rounded-md px-1.5 font-mono text-[11.5px]/[18px] font-medium ${
                active ? "bg-accent text-white" : "bg-chip text-chip-ink hover:bg-[#d9e7fc]"
              }`}
            >
              {n}
            </button>
          );
        }
      }
      return <span key={i}>{part}</span>;
    });
  }

  /** The zero-hit refusal: a state the product is proud of, styled as such. */
  function renderNoAnswer(message: UiMessage, messageIndex: number) {
    const audit = auditLabel(message.meta);
    return (
      <div className="rounded-2xl bg-warn-surface p-5">
        <div className="flex items-center gap-2.5">
          <span className="grid size-[18px] shrink-0 place-items-center rounded-full bg-warn-badge text-xs font-semibold text-white">
            !
          </span>
          <span className="text-[14.5px] font-medium">{t.noAnswerTitle}</span>
        </div>
        <p className="mt-2.5 ml-7 text-[13.5px] leading-relaxed text-ink-tertiary">
          {message.content}
        </p>
        <p className="mt-3 ml-7 text-xs text-muted">{t.noAnswerNote(audit)}</p>
        <div className="mt-3 ml-7">
          <button
            type="button"
            onClick={() => copyAnswer(message.content, messageIndex)}
            className="text-[12.5px] font-medium text-link hover:underline"
          >
            {copiedIndex === messageIndex ? t.copied : t.copy}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div ref={scrollerRef} className="flex-1 overflow-y-auto">
      {messages.length === 0 && (
        <div className="flex h-full items-center justify-center px-8 text-center">
          <div>
            <p className="text-[17px] font-medium text-ink">{t.emptyTitle}</p>
            <p className="mt-1 text-sm text-muted">{t.emptySub}</p>
          </div>
        </div>
      )}
      <div className="mx-auto max-w-[720px] px-8 pt-10 pb-6">
        <ul className="flex flex-col">
          {messages.map((message, messageIndex) => {
            if (message.role === "user") {
              return (
                <li key={messageIndex} className="mt-10 flex justify-end first:mt-0">
                  <span className="max-w-[440px] rounded-[20px] rounded-br-[6px] bg-accent px-4 py-2.5 text-[15px] leading-normal whitespace-pre-wrap text-white">
                    {message.content}
                  </span>
                </li>
              );
            }

            const isLast = messageIndex === messages.length - 1;
            const sources = message.sources ?? [];
            const settled = !(isLast && busy);
            const noAnswer =
              message.sources !== undefined && sources.length === 0 && message.content !== "";
            const documentCount = new Set(sources.map((source) => source.document_id)).size;
            const audit = auditLabel(message.meta);
            const seconds = message.meta !== undefined ? formatAnswerSeconds(message.meta) : null;
            const panelOpenHere = panel !== null && panel.messageIndex === messageIndex;

            return (
              <li key={messageIndex} className="mt-7">
                {message.content === "" && isLast && status === "retrieving" ? (
                  <p className="text-[15px] text-muted">{t.searching}</p>
                ) : noAnswer && settled ? (
                  renderNoAnswer(message, messageIndex)
                ) : (
                  <>
                    <div className="text-[16px] leading-[1.8] whitespace-pre-wrap text-ink">
                      {renderAssistantText(message.content, messageIndex, sources.length)}
                    </div>
                    {settled && sources.length > 0 && (
                      <div className="mt-5 flex items-center gap-3">
                        <button
                          type="button"
                          onClick={() => onToggleSources(messageIndex)}
                          className="inline-flex items-center gap-2 rounded-full bg-surface px-[15px] py-2 text-[12.5px] font-medium text-link select-none hover:bg-surface-hover"
                        >
                          <span>{panelOpenHere ? t.hideSources : t.sources}</span>
                          <span className="font-mono text-[11px] font-normal text-muted">
                            {sources.length}
                          </span>
                        </button>
                        <span className="text-[11.5px] text-muted">
                          {t.meta(documentCount)}
                          {seconds !== null ? <> · {seconds}</> : null}
                          {audit !== null ? <> · {t.audit} №{audit}</> : null}
                        </span>
                        <button
                          type="button"
                          onClick={() => copyAnswer(message.content, messageIndex)}
                          className="ml-auto text-xs font-medium text-link hover:underline"
                        >
                          {copiedIndex === messageIndex ? t.copied : t.copy}
                        </button>
                      </div>
                    )}
                  </>
                )}
              </li>
            );
          })}
        </ul>
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
