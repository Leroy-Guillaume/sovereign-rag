import { useEffect, useMemo, useState } from "react";
import { Outlet } from "react-router";
import { getApiKey, setApiKey } from "./api";
import { APP_COPY } from "./lib/appCopy";
import { useLang } from "./lib/lang";
import { beginLogin, fetchAuthConfig, oidcSession, type OidcConfig } from "./lib/oidc";

export interface AppOutletContext {
  /** Views call this on ApiError.status === 401 to open the API-key modal. */
  onUnauthorized: () => void;
}

/**
 * Shell for the authenticated app (/chat, /admin). Each view brings its own
 * chrome (sidebar or top bar); the shell only owns the API-key modal.
 */
export default function App() {
  const [showKeyModal, setShowKeyModal] = useState(
    getApiKey() === null && oidcSession() === null,
  );
  const [keyDraft, setKeyDraft] = useState("");
  const [idp, setIdp] = useState<OidcConfig | null>(null);
  const { lang } = useLang();
  const t = APP_COPY[lang].modal;

  useEffect(() => {
    if (!showKeyModal) return;
    let cancelled = false;
    fetchAuthConfig()
      .then((config) => {
        if (!cancelled) setIdp(config);
      })
      .catch(() => {
        // Backend unreachable: the key input still renders; errors surface
        // on the first real request.
      });
    return () => {
      cancelled = true;
    };
  }, [showKeyModal]);

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
            <h2 className="text-lg font-semibold tracking-tight">{t.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-tertiary">
              {t.bodyBefore}
              <code className="font-mono text-[13px] text-ink-secondary">AUTH_API_KEYS</code>
              {t.bodyAfter}
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
              {t.save}
            </button>
            {idp !== null && (
              <>
                <button
                  type="button"
                  onClick={() => void beginLogin(idp)}
                  className="mt-3 w-full rounded-full bg-surface px-4 py-2.5 text-sm font-medium text-link hover:bg-surface-hover"
                >
                  {t.idpButton}
                </button>
                <p className="mt-2 text-center text-xs text-muted">{t.idpHint}</p>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
