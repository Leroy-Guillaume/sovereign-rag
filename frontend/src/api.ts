import { freshOidcToken } from "./lib/oidc";
import type {
  AdminMetrics,
  ChatDeltaData,
  ChatDoneData,
  ChatErrorData,
  ChatStartData,
  ConversationDetail,
  ConversationOut,
  DocumentOut,
  Me,
  PermissionOut,
  SourceOut,
} from "./types";

// --- API key (demo auth: stored in this browser only; OIDC lands in P2) -----

const API_KEY_STORAGE = "sovereign-rag.apiKey";

export function getApiKey(): string | null {
  return localStorage.getItem(API_KEY_STORAGE);
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key);
}

// --- Fetch wrapper -----------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface RequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: BodyInit;
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key === null ? {} : { Authorization: `Bearer ${key}` };
}

/** OIDC session first (refreshed when stale), API key as the fallback. */
async function bearerHeaders(): Promise<Record<string, string>> {
  const token = await freshOidcToken();
  if (token !== null) return { Authorization: `Bearer ${token}` };
  return authHeaders();
}

/**
 * FastAPI wraps error messages as {"detail": ...}; surface the message,
 * never the raw JSON envelope, and fall back to the HTTP status text.
 */
async function toApiError(response: Response): Promise<ApiError> {
  const raw = await response.text();
  let message = response.statusText;
  if (raw !== "") {
    try {
      const parsed: unknown = JSON.parse(raw);
      const detail = (parsed as { detail?: unknown }).detail;
      message = typeof detail === "string" ? detail : raw;
    } catch {
      message = raw;
    }
  }
  return new ApiError(response.status, message);
}

/**
 * Thin fetch wrapper: attaches the Authorization header and normalizes
 * failures into ApiError. A 401 is surfaced to the caller so the app shell
 * can open the API-key modal.
 */
export async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const response = await fetch(path, {
    method: init.method ?? "GET",
    headers: { ...(await bearerHeaders()), ...init.headers },
    body: init.body,
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as unknown as T; // DELETE /api/documents/{id}
  }
  return (await response.json()) as T;
}

// --- Endpoint helpers ----------------------------------------------------------

export function listDocuments(): Promise<DocumentOut[]> {
  return request<DocumentOut[]>("/api/documents");
}

export function uploadDocument(file: File): Promise<DocumentOut> {
  const form = new FormData();
  form.append("file", file);
  // No Content-Type header: the browser sets multipart/form-data + boundary.
  return request<DocumentOut>("/api/documents", { method: "POST", body: form });
}

export function deleteDocument(id: string): Promise<void> {
  return request<void>(`/api/documents/${id}`, { method: "DELETE" });
}

export function getAdminMetrics(days: number): Promise<AdminMetrics> {
  return request<AdminMetrics>(`/api/admin/metrics?days=${days}`);
}

export function listPermissions(documentId: string): Promise<PermissionOut[]> {
  return request<PermissionOut[]>(`/api/documents/${documentId}/permissions`);
}

export function grantPermission(documentId: string, principal: string): Promise<void> {
  return request<void>(`/api/documents/${documentId}/permissions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ principal }),
  });
}

export function revokePermission(documentId: string, principal: string): Promise<void> {
  return request<void>(
    `/api/documents/${documentId}/permissions/${encodeURIComponent(principal)}`,
    { method: "DELETE" },
  );
}

/** "sk-····d4a2" style display form of the stored key (sidebar and admin bar). */
export function maskedApiKey(): string | null {
  const key = getApiKey();
  if (key === null) return null;
  return `${key.slice(0, 3)}····${key.slice(-4)}`;
}

export function listConversations(): Promise<ConversationOut[]> {
  return request<ConversationOut[]>("/api/conversations");
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/api/conversations/${id}`);
}

export function me(): Promise<Me> {
  return request<Me>("/api/me");
}

/** Download the conversation export; resolves the server-suggested filename. */
export async function downloadConversation(id: string): Promise<void> {
  // Plain <a href> cannot carry the Authorization header, so fetch the blob
  // and hand it to the browser through a transient object URL.
  const response = await fetch(`/api/conversations/${id}/export`, { headers: await bearerHeaders() });
  if (!response.ok) {
    throw await toApiError(response);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "conversation.json";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

// --- SSE: POST /api/chat -------------------------------------------------------

export interface ChatStreamHandlers {
  onStart: (data: ChatStartData) => void;
  onSources: (data: SourceOut[]) => void;
  onDelta: (data: ChatDeltaData) => void;
  onDone: (data: ChatDoneData) => void;
  onError: (data: ChatErrorData) => void;
}

/**
 * Consume the POST /api/chat SSE stream.
 *
 * EventSource cannot send a POST body or an Authorization header, so this is
 * a hand-rolled parser, deliberately pedagogical: buffer the decoded bytes,
 * split on "\n\n" (the SSE event boundary), then read the "event: " and
 * "data: " lines of each block. Lines starting with ":" are SSE comments
 * (the server's ": ping" heartbeat) and are ignored per the spec.
 *
 * Aborting the signal (stop button, component unmount) ends the function
 * silently; the backend sees the disconnect and persists the partial answer
 * with error_code='client_disconnect'.
 */
export async function streamChat(
  body: { conversation_id: string | null; message: string },
  handlers: ChatStreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await bearerHeaders()) },
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok || response.body === null) {
      const detail = await response.text();
      throw new ApiError(response.status, detail !== "" ? detail : response.statusText);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? ""; // last element is an incomplete block
      for (const block of blocks) {
        dispatchBlock(block, handlers);
      }
    }
    if (buffer.trim() !== "") {
      dispatchBlock(buffer, handlers); // defensive: stream ended without trailing \n\n
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return; // user pressed stop or navigated away, not an error
    }
    throw err;
  }
}

function dispatchBlock(block: string, handlers: ChatStreamHandlers): void {
  let event = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // SSE comment, the ": ping" heartbeat
    if (line.startsWith("event: ")) event = line.slice("event: ".length);
    if (line.startsWith("data: ")) data = line.slice("data: ".length); // single-line JSON payloads
  }
  if (event === "" || data === "") return;
  switch (event) {
    case "start":
      handlers.onStart(JSON.parse(data) as ChatStartData);
      break;
    case "sources":
      handlers.onSources(JSON.parse(data) as SourceOut[]);
      break;
    case "delta":
      handlers.onDelta(JSON.parse(data) as ChatDeltaData);
      break;
    case "done":
      handlers.onDone(JSON.parse(data) as ChatDoneData);
      break;
    case "error":
      handlers.onError(JSON.parse(data) as ChatErrorData);
      break;
  }
}
