import { useCallback, useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router";
import { ApiError, deleteDocument, getAdminMetrics, listDocuments, me, uploadDocument } from "../api";
import type { AppOutletContext } from "../App";
import type { AdminMetrics, DocumentOut } from "../types";

const STATUS_STYLES: Record<DocumentOut["status"], string> = {
  processing: "bg-amber-950 text-amber-300",
  ready: "bg-emerald-950 text-emerald-300",
  failed: "bg-red-950 text-red-300",
};

function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return `${value}`;
}

function formatLatency(ms: number | null): string {
  if (ms === null) return "n/a";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} kB`;
  return `${bytes} B`;
}

export default function AdminView() {
  const { onUnauthorized } = useOutletContext<AppOutletContext>();
  const [access, setAccess] = useState<"loading" | "granted" | "forbidden">("loading");
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await listDocuments());
      setMetrics(await getAdminMetrics());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
    }
  }, [onUnauthorized]);

  useEffect(() => {
    let cancelled = false;
    me()
      .then((who) => {
        if (!cancelled) setAccess(who.roles.includes("admin") ? "granted" : "forbidden");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) onUnauthorized();
        setAccess("forbidden");
      });
    return () => {
      cancelled = true;
    };
  }, [onUnauthorized]);

  useEffect(() => {
    if (access === "granted") void refresh();
  }, [access, refresh]);

  // Poll every 2 s while any document is still processing (design §6: the
  // frontend polls document statuses at 2 s). The interval is torn down as
  // soon as nothing is processing anymore.
  useEffect(() => {
    if (access !== "granted") return;
    if (!documents.some((doc) => doc.status === "processing")) return;
    const timer = window.setInterval(() => {
      void refresh();
    }, 2000);
    return () => {
      window.clearInterval(timer);
    };
  }, [access, documents, refresh]);

  async function handleFiles(files: FileList | null) {
    const file = files?.item(0);
    if (file === null || file === undefined) return;
    setActionError(null);
    try {
      await uploadDocument(file);
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized();
        return;
      }
      setActionError(err instanceof Error ? err.message : "upload failed");
    }
  }

  async function handleDelete(id: string) {
    setActionError(null);
    try {
      await deleteDocument(id);
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized();
        return;
      }
      setActionError(err instanceof Error ? err.message : "delete failed");
    }
  }

  if (access === "loading") {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-neutral-500">
        Checking permissions…
      </div>
    );
  }

  if (access === "forbidden") {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="max-w-md rounded-xl border border-neutral-800 bg-neutral-900 p-6 text-center">
          <h2 className="text-lg font-semibold text-neutral-100">Admin access required</h2>
          <p className="mt-2 text-sm leading-relaxed text-neutral-400">
            Your API key is valid but does not carry the admin role. Ask an operator to add your
            user id to <code className="text-neutral-300">AUTH_ADMIN_USERS</code>, or switch to an
            admin key.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-neutral-100">Documents</h1>
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.md,.txt"
              className="hidden"
              onChange={(event) => {
                void handleFiles(event.target.files);
                event.target.value = ""; // allow re-selecting the same file
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
            >
              Upload document
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-neutral-300">Usage</span>
              <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400">
                {metrics ? `${metrics.window_days} days` : "…"}
              </span>
            </div>
            <div className="mt-3 text-2xl font-semibold text-neutral-100">
              {metrics ? formatCount(metrics.answers) : "…"}
              <span className="ml-1 text-sm font-normal text-neutral-400">answers</span>
            </div>
            <div className="mt-1 text-xs text-neutral-400">
              {metrics
                ? `${formatCount(metrics.conversations)} conversations · ${formatCount(metrics.errors)} errors`
                : ""}
            </div>
          </div>
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-neutral-300">Tokens</span>
              <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400">
                prompt / completion
              </span>
            </div>
            <div className="mt-3 text-2xl font-semibold text-neutral-100">
              {metrics ? formatCount(metrics.prompt_tokens) : "…"}
              <span className="mx-1 text-neutral-500">/</span>
              {metrics ? formatCount(metrics.completion_tokens) : "…"}
            </div>
            <div className="mt-1 text-xs text-neutral-400">
              {metrics && metrics.top_cited.length > 0
                ? `top cited: ${metrics.top_cited[0].filename}`
                : ""}
            </div>
          </div>
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-neutral-300">Latency</span>
              <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400">
                p50 / p95
              </span>
            </div>
            <div className="mt-3 text-2xl font-semibold text-neutral-100">
              {metrics ? formatLatency(metrics.generation.p50_ms) : "…"}
              <span className="mx-1 text-neutral-500">/</span>
              {metrics ? formatLatency(metrics.generation.p95_ms) : "…"}
            </div>
            <div className="mt-1 text-xs text-neutral-400">
              {metrics
                ? `retrieval ${formatLatency(metrics.retrieval.p50_ms)} / ${formatLatency(metrics.retrieval.p95_ms)}`
                : ""}
            </div>
          </div>
        </div>

        {actionError !== null && (
          <div className="mt-4 rounded-lg border border-red-900 bg-red-950 px-3 py-2 text-sm text-red-300">
            {actionError}
          </div>
        )}

        <table className="mt-4 w-full border-separate border-spacing-0 text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-neutral-500">
              <th className="border-b border-neutral-800 px-3 py-2">File</th>
              <th className="border-b border-neutral-800 px-3 py-2">Type</th>
              <th className="border-b border-neutral-800 px-3 py-2">Size</th>
              <th className="border-b border-neutral-800 px-3 py-2">Status</th>
              <th className="border-b border-neutral-800 px-3 py-2">Uploaded</th>
              <th className="border-b border-neutral-800 px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => (
              <tr key={doc.id} className="text-neutral-300">
                <td className="border-b border-neutral-900 px-3 py-2">{doc.filename}</td>
                <td className="border-b border-neutral-900 px-3 py-2 font-mono text-xs">
                  {doc.content_type}
                </td>
                <td className="border-b border-neutral-900 px-3 py-2">
                  {formatSize(doc.size_bytes)}
                </td>
                <td className="border-b border-neutral-900 px-3 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLES[doc.status]}`}>
                    {doc.status}
                  </span>
                  {doc.error !== null && (
                    <span className="ml-2 text-xs text-red-400">{doc.error}</span>
                  )}
                </td>
                <td className="border-b border-neutral-900 px-3 py-2 text-neutral-500">
                  {new Date(doc.created_at).toLocaleString()}
                </td>
                <td className="border-b border-neutral-900 px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => void handleDelete(doc.id)}
                    className="text-xs text-neutral-500 hover:text-red-400"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {documents.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-neutral-500">
                  No documents yet. Upload one to make it searchable.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
