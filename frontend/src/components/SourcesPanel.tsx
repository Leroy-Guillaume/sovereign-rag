import { useEffect, useRef } from "react";
import type { AnswerMeta } from "../hooks/useChatStream";
import { auditLabel, formatScore } from "../lib/format";
import type { SourceOut } from "../types";

interface SourcesPanelProps {
  sources: SourceOut[];
  /** 1-based rank of the answer within the conversation ("Sources · réponse N"). */
  answerNumber: number;
  /** 1-based citation number to highlight, when opened via a marker. */
  activeSource: number | null;
  meta: AnswerMeta | undefined;
  /** The user question this answer responds to; part of the JSON export. */
  question: string | null;
  answer: string;
  onClose: () => void;
  onSelect: (source: number) => void;
}

function rankLabel(rank: number | null): string {
  return rank === null ? "n/a" : String(rank);
}

export default function SourcesPanel({
  sources,
  answerNumber,
  activeSource,
  meta,
  question,
  answer,
  onClose,
  onSelect,
}: SourcesPanelProps) {
  const cardRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const documentCount = new Set(sources.map((source) => source.document_id)).size;
  const maxScore = Math.max(...sources.map((source) => source.score), 0);
  const audit = auditLabel(meta);

  // answerNumber keeps this firing when the same citation number is opened
  // from a different answer (activeSource alone would not change).
  useEffect(() => {
    if (activeSource === null) return;
    cardRefs.current[activeSource - 1]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeSource, answerNumber]);

  function exportJson() {
    // The audit snapshot as the user saw it: question, answer, and the exact
    // excerpts/scores/ranks. Backend persistence survives document deletion;
    // this export is the local, hand-to-an-auditor copy of the same facts.
    const payload = {
      audit_message_id: meta?.messageId ?? null,
      question,
      answer,
      sources,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `audit-${audit ?? "reponse"}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <aside className="flex w-[360px] shrink-0 flex-col border-l border-black/[0.07] bg-surface-raised">
      <div className="flex h-[52px] shrink-0 items-center justify-between border-b border-black/[0.06] pr-4 pl-5">
        <div>
          <div className="text-[13px] font-medium">Sources · réponse {answerNumber}</div>
          <div className="mt-0.5 text-[10.5px] text-muted">
            {sources.length} passage{sources.length > 1 ? "s" : ""} · {documentCount} document
            {documentCount > 1 ? "s" : ""} · fusion RRF
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fermer le panneau des sources"
          className="grid size-6 shrink-0 place-items-center rounded-full bg-black/[0.06] text-xs text-ink-tertiary hover:bg-black/[0.12]"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3.5">
        {sources.map((source, i) => {
          const n = i + 1;
          const active = activeSource === n;
          const where = [
            source.section,
            source.page !== null ? `p. ${source.page}` : null,
          ].filter((part): part is string => part !== null);
          return (
            <button
              type="button"
              key={source.chunk_id}
              ref={(element) => {
                cardRefs.current[i] = element;
              }}
              onClick={() => onSelect(n)}
              className={`mt-2.5 block w-full cursor-pointer rounded-[14px] bg-white p-4 text-left first:mt-0 ${
                active
                  ? "shadow-[0_0_0_1.5px_var(--color-accent),0_6px_18px_rgba(0,113,227,0.13)]"
                  : "shadow-[0_1px_3px_rgba(0,0,0,0.08)] hover:shadow-[0_1px_6px_rgba(0,0,0,0.14)]"
              }`}
            >
              <div className="flex items-baseline gap-2.5">
                <span
                  className={`shrink-0 font-mono text-[11px] font-medium ${
                    active ? "text-accent" : "text-muted"
                  }`}
                >
                  {n}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] font-medium">{source.filename}</div>
                  {where.length > 0 && (
                    <div className="mt-0.5 truncate text-[10.5px] text-muted">
                      {where.join(" · ")}
                    </div>
                  )}
                </div>
                <span className="font-mono text-[10.5px] text-muted">
                  {formatScore(source.score)}
                </span>
              </div>
              <p
                className={`mt-2 text-xs leading-relaxed text-ink-secondary ${
                  active ? "" : "line-clamp-5"
                }`}
              >
                « {source.excerpt} »
              </p>
              <div className="mt-3 flex items-center gap-2.5">
                <span className="relative h-[3px] flex-1 rounded-sm bg-black/[0.09]">
                  <span
                    className={`absolute inset-y-0 left-0 rounded-sm ${
                      active ? "bg-accent" : "bg-faint"
                    }`}
                    style={{ width: `${maxScore > 0 ? (source.score / maxScore) * 100 : 0}%` }}
                  />
                </span>
                <span className="font-mono text-[10px] text-muted">
                  vect {rankLabel(source.vec_rank)} · txt {rankLabel(source.fts_rank)}
                </span>
              </div>
            </button>
          );
        })}
      </div>

      <div className="flex shrink-0 items-start gap-2.5 border-t border-black/[0.06] px-5 py-3.5">
        <svg
          width="13"
          height="15"
          viewBox="0 0 13 15"
          aria-hidden="true"
          className="mt-0.5 shrink-0 text-muted"
        >
          <path
            d="M6.5 0 13 2.5v4.2c0 3.6-2.8 6.9-6.5 8.3C2.8 13.6 0 10.3 0 6.7V2.5z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.1"
          />
          <path d="m4 7 1.8 1.8L9.3 5.5" fill="none" stroke="currentColor" strokeWidth="1.2" />
        </svg>
        <div className="text-[10.5px] leading-relaxed text-muted">
          Instantané d'audit{audit !== null ? <> №{audit}</> : null} : extraits, scores et rangs
          conservés même si le document est supprimé.{" "}
          <button
            type="button"
            onClick={exportJson}
            className="font-medium text-link hover:underline"
          >
            Exporter (json)
          </button>
        </div>
      </div>
    </aside>
  );
}
