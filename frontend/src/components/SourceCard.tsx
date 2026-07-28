import type { SourceOut } from "../types";

interface SourceCardProps {
  source: SourceOut;
  /** 1-based citation number — matches the [n] markers in the answer. */
  index: number;
  /** DOM id targeted by the [n] citation buttons in MessageList. */
  anchorId: string;
  highlighted: boolean;
}

export default function SourceCard({ source, index, anchorId, highlighted }: SourceCardProps) {
  const where = [source.section, source.page !== null ? `page ${source.page}` : null]
    .filter((part): part is string => part !== null)
    .join(" — ");

  return (
    <div
      id={anchorId}
      className={`rounded-lg border p-3 text-xs transition-colors ${
        highlighted ? "border-indigo-500 bg-indigo-950/40" : "border-neutral-800 bg-neutral-900"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-neutral-200">
          [{index}] {source.filename}
        </span>
        <span className="shrink-0 font-mono text-neutral-500">score {source.score.toFixed(3)}</span>
      </div>
      {where !== "" && <div className="mt-0.5 text-neutral-500">{where}</div>}
      <p className="mt-2 line-clamp-4 text-neutral-400">{source.excerpt}</p>
      <div className="mt-2 flex gap-1">
        {source.vec_rank !== null && (
          <span className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-neutral-400">
            vec #{source.vec_rank}
          </span>
        )}
        {source.fts_rank !== null && (
          <span className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-neutral-400">
            fts #{source.fts_rank}
          </span>
        )}
      </div>
    </div>
  );
}
