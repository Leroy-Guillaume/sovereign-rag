import { useEffect } from "react";
import { useLocation, useOutletContext, useSearchParams } from "react-router";
import { ApiError, getConversation } from "../api";
import type { AppOutletContext } from "../App";
import MessageInput from "../components/MessageInput";
import MessageList from "../components/MessageList";
import { useChatStream } from "../hooks/useChatStream";

export default function ChatView() {
  const { onUnauthorized } = useOutletContext<AppOutletContext>();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("c");
  const { status, messages, conversationId, error, send, stop, hydrate } =
    useChatStream(onUnauthorized);
  const busy = status === "retrieving" || status === "streaming";

  // Hydrate from the URL (?c=<id>). Keyed on location.key on purpose: it
  // changes on every router navigation (sidebar click, "New conversation")
  // and NEVER during streaming, so this effect cannot clobber an in-flight
  // stream. requestedId/conversationId are read from the render that the
  // navigation itself produced, so they are always fresh here.
  useEffect(() => {
    if (requestedId === null) {
      hydrate(null, []);
      return;
    }
    if (requestedId === conversationId) {
      return; // already live in memory (we just streamed it)
    }
    let cancelled = false;
    getConversation(requestedId)
      .then((detail) => {
        if (cancelled) return;
        hydrate(
          detail.id,
          detail.messages.map((m) => ({ role: m.role, content: m.content, sources: m.sources })),
        );
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          onUnauthorized();
          return;
        }
        hydrate(null, []); // 404 (not ours or deleted): fall back to a fresh chat
      });
    return () => {
      cancelled = true;
    };
  }, [location.key]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <MessageList messages={messages} status={status} />
      <div className="border-t border-neutral-800 bg-neutral-950 p-4">
        <div className="mx-auto max-w-3xl">
          {error !== null && (
            <div className="mb-2 rounded-lg border border-red-900 bg-red-950 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}
          <div className="flex items-end gap-2">
            <MessageInput disabled={busy} onSend={(text) => void send(text)} />
            {busy && (
              <button
                type="button"
                onClick={stop}
                className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:border-red-700 hover:text-red-300"
              >
                Stop
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
