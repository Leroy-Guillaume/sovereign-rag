import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, streamChat } from "../api";
import type { SourceOut } from "../types";

export type ChatStatus = "idle" | "retrieving" | "streaming" | "error";

/** Facts about a completed answer, shown in the meta row and audit footer. */
export interface AnswerMeta {
  /** Backend message id; its first 4 hex chars label the audit snapshot. */
  messageId: string;
  /** Stage latencies; null on messages hydrated from history (not persisted per stage in the listing). */
  retrievalMs: number | null;
  generationMs: number | null;
}

export interface UiMessage {
  role: "user" | "assistant";
  content: string;
  sources?: SourceOut[];
  meta?: AnswerMeta;
}

/** Apply an update to the trailing (pending) assistant message, immutably. */
function withPendingAssistant(
  messages: UiMessage[],
  update: (message: UiMessage) => UiMessage,
): UiMessage[] {
  if (messages.length === 0) return messages;
  const last = messages[messages.length - 1];
  if (last.role !== "assistant") return messages;
  return [...messages.slice(0, -1), update(last)];
}

export function useChatStream(onUnauthorized: () => void) {
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // Abort any in-flight stream on unmount; the backend sees the disconnect
    // and persists the partial answer with error_code='client_disconnect'.
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  /** Replace the whole local state (load a conversation, or reset to blank). */
  const hydrate = useCallback((id: string | null, history: UiMessage[]) => {
    abortRef.current?.abort();
    setConversationId(id);
    setMessages(history);
    setStatus("idle");
    setError(null);
  }, []);

  const send = useCallback(
    async (text: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setError(null);
      setStatus("retrieving");
      // Optimistic user message + empty pending assistant message that the
      // SSE handlers below fill in as events arrive.
      setMessages((prev) => [
        ...prev,
        { role: "user", content: text },
        { role: "assistant", content: "" },
      ]);
      try {
        await streamChat(
          { conversation_id: conversationId, message: text },
          {
            onStart: (data) => {
              setConversationId(data.conversation_id);
            },
            onSources: (data) => {
              setMessages((prev) => withPendingAssistant(prev, (m) => ({ ...m, sources: data })));
            },
            onDelta: (data) => {
              setStatus("streaming");
              setMessages((prev) =>
                withPendingAssistant(prev, (m) => ({ ...m, content: m.content + data.text })),
              );
            },
            onDone: (data) => {
              setMessages((prev) =>
                withPendingAssistant(prev, (m) => ({
                  ...m,
                  meta: {
                    messageId: data.message_id,
                    retrievalMs: data.retrieval_ms,
                    generationMs: data.generation_ms,
                  },
                })),
              );
              setStatus("idle");
            },
            onError: (data) => {
              setStatus("error");
              setError(`${data.code}: ${data.detail}`);
            },
          },
          controller.signal,
        );
        // Stream closed (normally, or via abort): settle back to idle unless
        // the terminal SSE error event already put us in the error state.
        setStatus((current) => (current === "error" ? current : "idle"));
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          onUnauthorized();
        }
        setStatus("error");
        setError(err instanceof Error ? err.message : "request failed");
      }
    },
    [conversationId, onUnauthorized],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStatus("idle");
  }, []);

  return { status, messages, conversationId, error, send, stop, hydrate };
}
