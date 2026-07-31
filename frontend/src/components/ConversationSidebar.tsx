import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { listConversations } from "../api";
import type { ConversationOut } from "../types";

export default function ConversationSidebar() {
  const [conversations, setConversations] = useState<ConversationOut[]>([]);
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const activeId = searchParams.get("c");

  useEffect(() => {
    let cancelled = false;
    listConversations()
      .then((items) => {
        if (!cancelled) setConversations(items);
      })
      .catch(() => {
        // No key yet, or backend unreachable: an empty list is the right
        // fallback — the key modal / view-level errors handle the rest.
      });
    return () => {
      cancelled = true;
    };
  }, [location.key]);

  return (
    <nav className="flex flex-1 flex-col overflow-y-auto p-2">
      <Link
        to="/"
        className="mb-2 rounded-lg border border-dashed border-neutral-700 px-3 py-2 text-center text-sm text-neutral-400 hover:border-neutral-500 hover:text-neutral-200"
      >
        + New conversation
      </Link>
      <ul className="flex flex-col gap-1">
        {conversations.map((conversation) => (
          <li key={conversation.id}>
            <Link
              to={`/?c=${conversation.id}`}
              className={`block truncate rounded-lg px-3 py-2 text-sm ${
                conversation.id === activeId
                  ? "bg-neutral-800 text-neutral-100"
                  : "text-neutral-400 hover:bg-neutral-800/60 hover:text-neutral-200"
              }`}
            >
              {conversation.title}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
