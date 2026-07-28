// Hand-written mirrors of the backend Pydantic response models (schemas.py).
// Deliberately not generated: ten stable types do not justify an
// openapi-typescript build step. The backend snapshots the SSE event schema
// in its own test suite, which is where contract drift gets caught.

export interface DocumentOut {
  id: string;
  filename: string;
  content_type: "pdf" | "docx" | "md" | "txt";
  size_bytes: number;
  status: "processing" | "ready" | "failed";
  error: string | null;
  owner_id: string;
  created_at: string;
  /** Present and true when POST /api/documents matched an existing sha256. */
  deduplicated?: boolean;
}

export interface SourceOut {
  chunk_id: string;
  document_id: string;
  filename: string;
  section: string | null;
  page: number | null;
  /** Chunk content truncated to 500 chars by the backend. */
  excerpt: string;
  /** Fused RRF score. */
  score: number;
  vec_rank: number | null;
  fts_rank: number | null;
}

export interface MessageOut {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: SourceOut[];
  model: string | null;
  created_at: string;
}

export interface ConversationOut {
  id: string;
  title: string;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  created_at: string;
  messages: MessageOut[];
}

export interface Me {
  id: string;
  roles: string[];
}

// --- SSE payloads for POST /api/chat, in stream order -----------------------

export interface ChatStartData {
  conversation_id: string;
}

export interface ChatDeltaData {
  text: string;
}

export interface ChatDoneData {
  message_id: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  retrieval_ms: number;
  generation_ms: number;
}

export interface ChatErrorData {
  code: string;
  detail: string;
}

/** Discriminated union of every event the /api/chat stream can emit. */
export type ChatEvent =
  | { event: "start"; data: ChatStartData }
  | { event: "sources"; data: SourceOut[] }
  | { event: "delta"; data: ChatDeltaData }
  | { event: "done"; data: ChatDoneData }
  | { event: "error"; data: ChatErrorData };
