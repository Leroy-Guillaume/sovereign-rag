import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { APP_COPY } from "../lib/appCopy";
import { useLang } from "../lib/lang";
import { completeLogin, fetchAuthConfig } from "../lib/oidc";

/** Lands here from the IdP redirect; exchanges the code, then enters the app. */
export default function AuthCallback() {
  const { lang } = useLang();
  const t = APP_COPY[lang].auth;
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const config = await fetchAuthConfig();
      if (config === null) throw new Error("OIDC is not configured");
      await completeLogin(config);
      if (!cancelled) await navigate("/chat", { replace: true });
    })().catch((err: unknown) => {
      if (!cancelled) setError(err instanceof Error ? err.message : String(err));
    });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <div className="flex h-screen items-center justify-center bg-surface font-sans text-ink">
      {error === null ? (
        <p className="text-sm text-muted">{t.callbackWorking}</p>
      ) : (
        <div className="max-w-md rounded-2xl bg-white p-7 text-center shadow-[0_1px_3px_rgba(0,0,0,0.07)]">
          <h2 className="text-lg font-semibold tracking-tight">{t.callbackFailed}</h2>
          <p className="mt-2 font-mono text-xs text-ink-tertiary">{error}</p>
          <Link to="/chat" className="mt-4 inline-block text-sm font-medium text-link">
            {t.backToLogin}
          </Link>
        </div>
      )}
    </div>
  );
}
