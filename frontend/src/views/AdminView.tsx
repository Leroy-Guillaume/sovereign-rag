import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useOutletContext } from "react-router";
import {
  ApiError,
  deleteDocument,
  getAdminMetrics,
  grantPermission,
  listDocuments,
  listPermissions,
  maskedApiKey,
  me,
  revokePermission,
  uploadDocument,
} from "../api";
import type { AppOutletContext } from "../App";
import BrandHomeLink from "../components/BrandHomeLink";
import { APP_COPY } from "../lib/appCopy";
import {
  fmtDecimal,
  formatCount,
  formatDate,
  formatInt,
  formatLatency,
  formatRelative,
  formatSize,
} from "../lib/format";
import { LangSwitcher, useLang } from "../lib/lang";
import type { AdminMetrics, DocumentOut, PermissionOut } from "../types";

const DAY_OPTIONS = [7, 30, 90] as const;
type WindowDays = (typeof DAY_OPTIONS)[number];

const TABLE_COLUMNS = "grid-cols-[2.1fr_0.6fr_1.1fr_1.5fr_0.8fr_0.5fr]";
const CARD = "rounded-[18px] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.07)]";

function MetricTile(props: { label: string; value: ReactNode; caption: ReactNode }) {
  return (
    <div className={`${CARD} px-6 py-[22px]`}>
      <div className="text-xs font-medium text-muted">{props.label}</div>
      <div className="mt-2 text-[40px] font-semibold leading-[1.1] tracking-[-0.03em]">
        {props.value}
      </div>
      <div className="mt-2 text-[12.5px] text-ink-tertiary">{props.caption}</div>
    </div>
  );
}

export default function AdminView() {
  const { onUnauthorized } = useOutletContext<AppOutletContext>();
  const { lang } = useLang();
  const t = APP_COPY[lang].admin;
  const [access, setAccess] = useState<"loading" | "granted" | "forbidden">("loading");
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [permissionsByDoc, setPermissionsByDoc] = useState<Record<string, PermissionOut[]>>({});
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [days, setDays] = useState<WindowDays>(30);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [principalDraft, setPrincipalDraft] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleApiError = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized();
        return;
      }
      // A failed refresh must say so: silently keeping stale state renders
      // as "Aucun document" and frozen tiles, which reads as healthy.
      setActionError(err instanceof Error ? err.message : fallback);
    },
    [onUnauthorized],
  );

  // Metrics, documents and permissions load independently: the 2 s status
  // poll must not replay the per-document permissions fan-out, and switching
  // the 7/30/90 window must not refetch documents at all.
  const refreshMetrics = useCallback(async () => {
    try {
      setMetrics(await getAdminMetrics(days));
      setActionError(null);
    } catch (err) {
      handleApiError(err, t.errLoadMetrics);
    }
  }, [days, handleApiError]);

  const refreshDocuments = useCallback(
    async (withPermissions: boolean) => {
      try {
        const docs = await listDocuments();
        setDocuments(docs);
        if (withPermissions) {
          const perms = await Promise.all(docs.map((doc) => listPermissions(doc.id)));
          setPermissionsByDoc(
            Object.fromEntries(docs.map((doc, index) => [doc.id, perms[index]] as const)),
          );
        }
        setActionError(null);
      } catch (err) {
        handleApiError(err, t.errLoadDocuments);
      }
    },
    [handleApiError],
  );

  useEffect(() => {
    let cancelled = false;
    me()
      .then((who) => {
        if (!cancelled) setAccess(who.roles.includes("admin") ? "granted" : "forbidden");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          onUnauthorized();
          return;
        }
        // Only a definitive 403 means "not admin"; a network failure must
        // not accuse the user's key of lacking a role it may well have.
        if (err instanceof ApiError && err.status === 403) {
          setAccess("forbidden");
        } else {
          setAccess("granted");
          setActionError(err instanceof Error ? err.message : t.errVerify);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [onUnauthorized]);

  useEffect(() => {
    if (access === "granted") void refreshDocuments(true);
  }, [access, refreshDocuments]);

  useEffect(() => {
    if (access === "granted") void refreshMetrics();
  }, [access, refreshMetrics]);

  // Poll every 2 s while any document is still processing (design §6: the
  // frontend polls document statuses at 2 s). The interval is torn down as
  // soon as nothing is processing anymore.
  useEffect(() => {
    if (access !== "granted") return;
    if (!documents.some((doc) => doc.status === "processing")) return;
    const timer = window.setInterval(() => {
      void refreshDocuments(false);
    }, 2000);
    return () => {
      window.clearInterval(timer);
    };
  }, [access, documents, refreshDocuments]);

  async function handleFiles(files: FileList | null) {
    if (files === null || files.length === 0) return;
    setActionError(null);
    // Sequential on purpose: ingestion is CPU-bound on the backend and the
    // upload endpoint answers fast anyway (extraction happens async).
    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file);
      } catch (err) {
        handleApiError(err, t.errUpload(file.name));
        break;
      }
    }
    await refreshDocuments(true);
  }

  async function handleDelete(doc: DocumentOut) {
    const confirmed = window.confirm(t.confirmDelete(doc.filename));
    if (!confirmed) return;
    setActionError(null);
    try {
      await deleteDocument(doc.id);
      await refreshDocuments(true);
    } catch (err) {
      handleApiError(err, t.errDelete);
    }
  }

  async function refreshDocPermissions(id: string) {
    const perms = await listPermissions(id);
    setPermissionsByDoc((prev) => ({ ...prev, [id]: perms }));
  }

  async function handleGrant(id: string, principal: string) {
    const value = principal.trim();
    if (value === "") return;
    // Same rule as the backend schema; checking here gives a message instead
    // of a raw 422.
    if (!/^[^\s/]+$/.test(value)) {
      setActionError(t.invalidPrincipal);
      return;
    }
    setActionError(null);
    try {
      await grantPermission(id, value);
      await refreshDocPermissions(id);
      setPrincipalDraft("");
    } catch (err) {
      handleApiError(err, t.errShare);
    }
  }

  async function handleRevoke(id: string, principal: string) {
    setActionError(null);
    try {
      await revokePermission(id, principal);
      await refreshDocPermissions(id);
    } catch (err) {
      handleApiError(err, t.errRevoke);
    }
  }

  function toggleEditing(id: string) {
    setPrincipalDraft("");
    setEditingId((prev) => (prev === id ? null : id));
  }

  if (access === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-surface text-sm text-muted">
        {t.checking}
      </div>
    );
  }

  if (access === "forbidden") {
    return (
      <div className="flex h-screen items-center justify-center bg-surface p-6">
        <div className="max-w-md rounded-2xl bg-white p-7 text-center shadow-[0_1px_3px_rgba(0,0,0,0.07)]">
          <h2 className="text-lg font-semibold tracking-tight text-ink">{t.forbiddenTitle}</h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-tertiary">
            {t.forbiddenBefore}
            <code className="font-mono text-[13px] text-ink-secondary">AUTH_ADMIN_USERS</code>
            {t.forbiddenAfter}
          </p>
        </div>
      </div>
    );
  }

  const masked = maskedApiKey();
  const totalChunks = documents.reduce((sum, doc) => sum + (doc.chunk_count ?? 0), 0);
  const latestCreatedAt = documents.reduce<string | null>(
    (latest, doc) =>
      latest === null || new Date(doc.created_at) > new Date(latest) ? doc.created_at : latest,
    null,
  );
  const avgTokens =
    metrics !== null && metrics.answers > 0
      ? Math.round((metrics.prompt_tokens + metrics.completion_tokens) / metrics.answers)
      : null;
  const errorPct =
    metrics !== null && metrics.answers > 0
      ? fmtDecimal((metrics.errors / metrics.answers) * 100, 1)
      : null;
  const topCited = metrics?.top_cited ?? [];
  const maxCitations = topCited.reduce((max, entry) => Math.max(max, entry.citations), 0);

  return (
    <div className="flex h-screen flex-col bg-surface text-ink">
      <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-black/[0.07] bg-white px-8">
        <div className="flex items-center gap-[26px]">
          <BrandHomeLink />
          <nav className="flex gap-1 rounded-[9px] bg-[#f0f0f3] p-[3px]">
            <Link
              to="/chat"
              className="rounded-[7px] px-3.5 py-[5px] text-[12.5px] font-medium text-ink-secondary hover:text-ink"
            >
              {t.chatTab}
            </Link>
            <span className="rounded-[7px] bg-white px-3.5 py-[5px] text-[12.5px] font-medium shadow-[0_1px_2px_rgba(0,0,0,0.1)]">
              {t.adminTab}
            </span>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <LangSwitcher />
          {masked !== null && <span className="font-mono text-[11.5px] text-muted">{masked}</span>}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1376px] px-8 py-8">
          <div className="flex items-end justify-between">
            <div>
              <h1 className="text-[34px] font-semibold leading-[1.15] tracking-[-0.024em]">
                {t.title}
              </h1>
              <p className="mt-2 text-[14.5px] text-ink-tertiary">
                {t.subtitle(documents.length, formatInt(totalChunks))}
                {latestCreatedAt !== null && ` · ${t.lastAdded} ${formatRelative(latestCreatedAt)}`}
              </p>
            </div>
            <div className="flex items-center gap-3.5">
              <div className="flex gap-[3px] rounded-[9px] bg-[#ebebef] p-[3px]">
                {DAY_OPTIONS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setDays(option)}
                    className={`rounded-[7px] px-3 py-[5px] text-xs font-medium ${
                      days === option
                        ? "bg-white shadow-[0_1px_2px_rgba(0,0,0,0.1)]"
                        : "text-ink-tertiary hover:text-ink"
                    }`}
                  >
                    {option} {t.day}
                  </button>
                ))}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.md,.txt"
                multiple
                className="hidden"
                onChange={(event) => {
                  void handleFiles(event.target.files);
                  event.target.value = ""; // allow re-selecting the same file
                }}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="rounded-full bg-accent px-[18px] py-[9px] text-[13px] font-medium text-white hover:bg-accent-hover"
              >
                {t.upload}
              </button>
            </div>
          </div>

          <div className="mt-[26px] grid grid-cols-4 gap-4">
            <MetricTile
              label={t.tiles.answers}
              value={metrics === null ? "…" : formatInt(metrics.answers)}
              caption={
                metrics === null ? "…" : t.tiles.conversations(formatInt(metrics.conversations))
              }
            />
            <MetricTile
              label={t.tiles.tokens}
              value={
                metrics === null ? (
                  "…"
                ) : (
                  <>
                    {formatCount(metrics.prompt_tokens)}{" "}
                    <span className="text-xl font-normal text-muted">
                      / {formatCount(metrics.completion_tokens)}
                    </span>
                  </>
                )
              }
              caption={
                metrics === null
                  ? "…"
                  : avgTokens !== null
                    ? t.tiles.perAnswer(formatInt(avgTokens))
                    : ""
              }
            />
            <MetricTile
              label={t.tiles.latency}
              value={
                metrics === null ? (
                  "…"
                ) : (
                  <>
                    {formatLatency(metrics.generation.p50_ms)}{" "}
                    <span className="text-xl font-normal text-muted">
                      / {formatLatency(metrics.generation.p95_ms)}
                    </span>
                  </>
                )
              }
              caption={
                metrics === null
                  ? "…"
                  : t.tiles.retrieval(
                      formatLatency(metrics.retrieval.p50_ms),
                      formatLatency(metrics.retrieval.p95_ms),
                    )
              }
            />
            <MetricTile
              label={t.tiles.errors}
              value={metrics === null ? "…" : formatInt(metrics.errors)}
              caption={
                metrics === null ? "…" : errorPct !== null ? t.tiles.errorPct(errorPct) : ""
              }
            />
          </div>

          {actionError !== null && (
            <div className="mt-4 rounded-xl bg-warn-surface px-4 py-2.5 text-sm text-warn">
              {actionError}
            </div>
          )}

          <div className="mt-4 grid grid-cols-[1fr_340px] items-start gap-4">
            <div className={`${CARD} overflow-hidden`}>
              <div className="flex items-center justify-between px-6 pt-5 pb-4">
                <span className="text-[15px] font-medium">{t.documents}</span>
                <span className="text-[11.5px] text-muted">{t.refreshNote}</span>
              </div>

              <div
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragActive(true);
                }}
                onDragLeave={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                    setDragActive(false);
                  }
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragActive(false);
                  void handleFiles(event.dataTransfer.files);
                }}
                className={`mx-6 rounded-[14px] border-[1.5px] border-dashed p-5 text-center ${
                  dragActive ? "border-accent bg-accent/5" : "border-black/15"
                }`}
              >
                <div className="text-[13.5px] font-medium">
                  {t.dropHere}
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="text-link hover:underline"
                  >
                    {t.browse}
                  </button>
                </div>
                <div className="mt-1 text-[11.5px] text-muted">{t.dropNote}</div>
              </div>

              <div
                className={`grid ${TABLE_COLUMNS} gap-3.5 px-6 pt-5 pb-2 text-[10.5px] font-medium tracking-wide text-muted uppercase`}
              >
                <span>{t.headers.file}</span>
                <span>{t.headers.size}</span>
                <span>{t.headers.status}</span>
                <span>{t.headers.sharing}</span>
                <span className="text-right">{t.headers.added}</span>
                <span />
              </div>

              {documents.map((doc) => {
                const perms = permissionsByDoc[doc.id] ?? [];
                const hasStar = perms.some((perm) => perm.principal === "*");
                const chunkSuffix =
                  doc.chunk_count === null || doc.chunk_count === undefined
                    ? ""
                    : ` · ${t.passages(formatInt(doc.chunk_count))}`;
                return (
                  <Fragment key={doc.id}>
                    <div
                      className={`grid ${TABLE_COLUMNS} items-center gap-3.5 border-t border-black/[0.07] px-6 py-3 text-[13px]`}
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium">{doc.filename}</div>
                        {doc.status === "failed" && doc.error !== null && (
                          <div className="mt-0.5 text-[11px] text-warn">{doc.error}</div>
                        )}
                      </div>
                      <span className="text-[12.5px] text-ink-tertiary">
                        {formatSize(doc.size_bytes)}
                      </span>
                      {doc.status === "ready" ? (
                        <span className="text-xs text-ok">
                          {t.ready}
                          {chunkSuffix}
                        </span>
                      ) : doc.status === "processing" ? (
                        <span className="animate-pulse text-xs text-link">{t.processing}</span>
                      ) : (
                        <span className="text-xs text-danger">{t.failed}</span>
                      )}
                      {hasStar ? (
                        <span className="min-w-0 truncate text-xs text-ink-secondary">
                          {t.everyone} ·{" "}
                          <button
                            type="button"
                            onClick={() => void handleRevoke(doc.id, "*")}
                            className="text-link hover:underline"
                          >
                            {t.revoke}
                          </button>
                        </span>
                      ) : perms.length === 0 ? (
                        <span className="min-w-0 truncate text-xs text-ink-secondary">
                          {t.private} ·{" "}
                          <button
                            type="button"
                            onClick={() => toggleEditing(doc.id)}
                            className="text-link hover:underline"
                          >
                            {t.share}
                          </button>
                        </span>
                      ) : (
                        <span className="flex min-w-0 items-center gap-1 text-xs text-ink-secondary">
                          <span className="truncate">
                            {perms.map((perm) => perm.principal).join(", ")}
                          </span>
                          <span className="shrink-0">·</span>
                          <button
                            type="button"
                            onClick={() => toggleEditing(doc.id)}
                            className="shrink-0 text-link hover:underline"
                          >
                            {t.manage}
                          </button>
                        </span>
                      )}
                      <span className="text-right text-xs text-muted">
                        {formatDate(doc.created_at)}
                      </span>
                      <span className="text-right">
                        <button
                          type="button"
                          onClick={() => void handleDelete(doc)}
                          className="text-xs text-muted hover:text-danger"
                        >
                          {t.remove}
                        </button>
                      </span>
                    </div>

                    {editingId === doc.id && (
                      <div className="border-t border-black/[0.07] bg-surface-raised px-6 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          {perms.length === 0 && (
                            <span className="text-xs text-muted">{t.noShares}</span>
                          )}
                          {perms.map((perm) => (
                            <span
                              key={perm.principal}
                              className="flex items-center gap-2 rounded-full bg-surface px-3 py-1 text-xs text-ink-secondary"
                            >
                              {perm.principal === "*" ? t.everyone : perm.principal}
                              <button
                                type="button"
                                onClick={() => void handleRevoke(doc.id, perm.principal)}
                                aria-label={`${t.revoke} ${perm.principal}`}
                                className="text-muted hover:text-danger"
                              >
                                ✕
                              </button>
                            </span>
                          ))}
                        </div>
                        <div className="mt-3 flex items-center gap-2">
                          <input
                            type="text"
                            value={principalDraft}
                            onChange={(event) => setPrincipalDraft(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") void handleGrant(doc.id, principalDraft);
                            }}
                            placeholder={t.principalPlaceholder}
                            className="w-72 rounded-full bg-white px-3.5 py-1.5 text-xs text-ink shadow-[inset_0_0_0_1px_rgba(0,0,0,0.1)] placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-accent"
                          />
                          <button
                            type="button"
                            onClick={() => void handleGrant(doc.id, principalDraft)}
                            className="rounded-full bg-accent px-4 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
                          >
                            {t.add}
                          </button>
                          {!hasStar && (
                            <button
                              type="button"
                              onClick={() => void handleGrant(doc.id, "*")}
                              className="text-xs text-link hover:underline"
                            >
                              {t.shareAll}
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </Fragment>
                );
              })}

              {documents.length === 0 && (
                <div className="border-t border-black/[0.07] py-8 text-center text-sm text-muted">
                  {t.empty}
                </div>
              )}
            </div>

            <div className="flex flex-col gap-4">
              <div className={`${CARD} p-6`}>
                <div className="text-[15px] font-medium">{t.topCited}</div>
                {metrics === null ? (
                  <div className="mt-2 text-[12.5px] text-ink-tertiary">…</div>
                ) : topCited.length === 0 ? (
                  <div className="mt-2 text-[12.5px] text-ink-tertiary">
                    {t.noCitations}
                  </div>
                ) : (
                  <div className="mt-[18px] grid grid-cols-[1fr_auto] items-center gap-x-3.5 gap-y-[11px]">
                    {topCited.map((entry, index) => (
                      <Fragment key={entry.filename}>
                        <div className="min-w-0">
                          <div className="truncate text-[12.5px]">{entry.filename}</div>
                          <span className="relative mt-1.5 block h-[3px] rounded-sm bg-black/[0.08]">
                            <span
                              className={`absolute inset-y-0 left-0 rounded-sm ${
                                index === 0 ? "bg-accent" : "bg-[#7eb4ef]"
                              }`}
                              style={{
                                width: `${maxCitations > 0 ? (entry.citations / maxCitations) * 100 : 0}%`,
                              }}
                            />
                          </span>
                        </div>
                        <span className="text-right font-mono text-[12.5px] font-medium">
                          {formatInt(entry.citations)}
                        </span>
                      </Fragment>
                    ))}
                  </div>
                )}
              </div>

              <div className={`${CARD} p-6`}>
                <div className="text-[15px] font-medium">{t.unanswered}</div>
                {metrics === null ? (
                  <div className="mt-2 text-[12.5px] text-ink-tertiary">…</div>
                ) : metrics.unanswered.length === 0 ? (
                  <div className="mt-2 text-[12.5px] leading-relaxed text-ink-tertiary">
                    {t.noUnanswered}
                  </div>
                ) : (
                  <>
                    <div className="mt-1.5 text-[12.5px] leading-relaxed text-ink-tertiary">
                      {t.unansweredIntro(
                        formatInt(
                          metrics.unanswered.reduce((sum, entry) => sum + entry.occurrences, 0),
                        ),
                      )}
                    </div>
                    <div className="mt-4 flex flex-col gap-2.5">
                      {metrics.unanswered.map((entry) => (
                        <div
                          key={entry.question}
                          className="flex items-baseline justify-between gap-3"
                        >
                          <span
                            className="truncate text-[12.5px] text-ink-secondary"
                            title={entry.question}
                          >
                            {entry.question}
                          </span>
                          <span className="shrink-0 font-mono text-xs text-muted">
                            {formatInt(entry.occurrences)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
