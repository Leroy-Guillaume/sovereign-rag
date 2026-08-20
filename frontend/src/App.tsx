import { useMemo, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { getApiKey, setApiKey } from "./api";
import ConversationSidebar from "./components/ConversationSidebar";

export interface AppOutletContext {
  /** Views call this on ApiError.status === 401 to open the API-key modal. */
  onUnauthorized: () => void;
}

export default function App() {
  const [showKeyModal, setShowKeyModal] = useState(getApiKey() === null);
  const [keyDraft, setKeyDraft] = useState("");
  const location = useLocation();
  const onAdmin = location.pathname.startsWith("/admin");

  // Stable identity: views hold effects that depend on this callback.
  const outletContext = useMemo<AppOutletContext>(
    () => ({ onUnauthorized: () => setShowKeyModal(true) }),
    [],
  );

  function saveKey() {
    const key = keyDraft.trim();
    if (key === "") return;
    setApiKey(key);
    // Full reload: the simplest correct way to make every view refetch with
    // the new key (nothing valuable is in flight while unauthorized).
    window.location.reload();
  }

  return (
    <div className="flex h-screen bg-neutral-950 font-sans text-neutral-200 antialiased">
      <aside className="flex w-72 shrink-0 flex-col border-r border-neutral-800 bg-neutral-900">
        <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
          <Link to="/" className="text-sm font-semibold tracking-tight text-neutral-100">
            sovereign-rag
          </Link>
          <Link
            to={onAdmin ? "/" : "/admin"}
            className="rounded px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200"
          >
            {onAdmin ? "Chat" : "Admin"}
          </Link>
        </div>
        <ConversationSidebar />
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <Outlet context={outletContext} />
      </main>

      {showKeyModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-md rounded-xl border border-neutral-700 bg-neutral-900 p-6 shadow-2xl">
            <h2 className="text-lg font-semibold text-neutral-100">API key required</h2>
            <p className="mt-2 text-sm leading-relaxed text-neutral-400">
              Paste one of the keys configured in{" "}
              <code className="text-neutral-300">AUTH_API_KEYS</code>. The key is kept in this
              browser's localStorage only (demo setup; OIDC lands in Phase 2).
            </p>
            <input
              type="password"
              value={keyDraft}
              onChange={(event) => setKeyDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") saveKey();
              }}
              placeholder="sk-demo"
              autoFocus
              className="mt-4 w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-200 placeholder:text-neutral-600 focus:border-indigo-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={saveKey}
              className="mt-4 w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
            >
              Save key
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
