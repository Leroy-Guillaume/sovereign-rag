import { useEffect, useRef, useState } from "react";
import { useLocation, useOutletContext, useSearchParams } from "react-router";
import { ApiError, getConversation } from "../api";
import type { AppOutletContext } from "../App";
import ConversationSidebar from "../components/ConversationSidebar";
import MessageInput from "../components/MessageInput";
import MessageList, { type SourcePanelState } from "../components/MessageList";
import SourcesPanel from "../components/SourcesPanel";
import { useChatStream } from "../hooks/useChatStream";

export default function ChatView() {
  const { onUnauthorized } = useOutletContext<AppOutletContext>();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("c");
  const { status, messages, conversationId, error, send, stop, hydrate } =
    useChatStream(onUnauthorized);
  // The sources panel is closed by default; a marker click or the "Sources"
  // pill opens it for one specific answer (design 2b).
  const [panel, setPanel] = useState<SourcePanelState | null>(null);
  const busy = status === "retrieving" || status === "streaming";
  // Mirror for async callbacks: a hydration fetch resolving mid-stream must
  // read the CURRENT streaming state, not the one captured at navigation.
  const busyRef = useRef(busy);
  busyRef.current = busy;

  // Hydrate from the URL (?c=<id>). Keyed on location.key on purpose: it
  // changes on every router navigation (sidebar click, "New conversation")
  // and NEVER during streaming, so this effect cannot clobber an in-flight
  // stream. requestedId/conversationId are read from the render that the
  // navigation itself produced, so they are always fresh here.
  useEffect(() => {
    setPanel(null); // sources belong to the conversation being left
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
        // A slow resolution can land after the user already sent a message
        // in this conversation: the live stream is fresher than the fetched
        // history, so hydrating now would abort it and discard their turn.
        if (cancelled || busyRef.current) return;
        hydrate(
          detail.id,
          detail.messages.map((m) => ({
            role: m.role,
            content: m.content,
            sources: m.sources,
            meta:
              m.role === "assistant"
                ? { messageId: m.id, retrievalMs: null, generationMs: null }
                : undefined,
          })),
        );
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          onUnauthorized();
          return;
        }
        if (busyRef.current) return;
        hydrate(null, []); // 404 (not ours or deleted): fall back to a fresh chat
      });
    return () => {
      cancelled = true;
    };
  }, [location.key]);

  const title = messages.find((message) => message.role === "user");
  const panelMessage = panel !== null ? messages[panel.messageIndex] : undefined;
  const panelSources = panelMessage?.sources ?? [];
  // "Sources · réponse N": rank of the open answer among assistant messages.
  const answerNumber =
    panel === null
      ? 0
      : messages
          .slice(0, panel.messageIndex + 1)
          .filter((message) => message.role === "assistant").length;
  const previousMessage = panel !== null ? messages[panel.messageIndex - 1] : undefined;
  const panelQuestion = previousMessage?.role === "user" ? previousMessage.content : null;

  return (
    <div className="flex h-screen bg-white">
      <ConversationSidebar />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-[52px] shrink-0 items-center border-b border-black/[0.07] px-7">
          <span className="truncate text-[13.5px] font-medium">
            {title !== undefined ? title.content : "Nouvelle conversation"}
          </span>
        </div>

        <MessageList
          messages={messages}
          status={status}
          panel={panel}
          onToggleSources={(messageIndex) =>
            setPanel((current) =>
              current?.messageIndex === messageIndex
                ? null
                : { messageIndex, activeSource: null },
            )
          }
          onOpenSource={(messageIndex, source) =>
            setPanel({ messageIndex, activeSource: source })
          }
        />

        <div className="shrink-0 border-t border-black/[0.07] px-8 pt-4 pb-[22px]">
          <div className="mx-auto max-w-[720px]">
            {error !== null && (
              <div className="mb-3 rounded-xl bg-warn-surface px-4 py-2.5 text-sm text-warn">
                {error}
              </div>
            )}
            <MessageInput busy={busy} onSend={(text) => void send(text)} onStop={stop} />
          </div>
        </div>
      </main>

      {panel !== null && panelSources.length > 0 && (
        <SourcesPanel
          sources={panelSources}
          answerNumber={answerNumber}
          activeSource={panel.activeSource}
          meta={panelMessage?.meta}
          question={panelQuestion}
          answer={panelMessage?.content ?? ""}
          onClose={() => setPanel(null)}
          onSelect={(source) =>
            setPanel((current) =>
              current === null ? current : { ...current, activeSource: source },
            )
          }
        />
      )}
    </div>
  );
}
