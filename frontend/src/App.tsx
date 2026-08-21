import { useMemo, useState } from "react";
import { Outlet } from "react-router";
import { getApiKey, setApiKey } from "./api";

export interface AppOutletContext {
  /** Views call this on ApiError.status === 401 to open the API-key modal. */
  onUnauthorized: () => void;
}

/**
 * Shell for the authenticated app (/chat, /admin). Each view brings its own
 * chrome (sidebar or top bar); the shell only owns the API-key modal.
 */
export default function App() {
  const [showKeyModal, setShowKeyModal] = useState(getApiKey() === null);
  const [keyDraft, setKeyDraft] = useState("");

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
    <div className="h-screen bg-white font-sans text-ink antialiased">
      <Outlet context={outletContext} />

      {showKeyModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-7 shadow-2xl">
            <h2 className="text-lg font-semibold tracking-tight">Clé API requise</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-tertiary">
              Collez une des clés configurées dans{" "}
              <code className="font-mono text-[13px] text-ink-secondary">AUTH_API_KEYS</code>. Elle
              reste dans le localStorage de ce navigateur (authentification de démonstration, OIDC
              en phase 2).
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
              className="mt-5 w-full rounded-xl bg-surface px-4 py-2.5 text-sm text-ink placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <button
              type="button"
              onClick={saveKey}
              className="mt-4 w-full rounded-full bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover"
            >
              Enregistrer la clé
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
