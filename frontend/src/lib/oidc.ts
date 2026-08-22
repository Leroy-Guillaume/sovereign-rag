// OIDC Authorization Code + PKCE for the SPA, against the operator's IdP.
// No client secret exists (public client): the verifier/challenge pair is
// the proof. Tokens live in localStorage next to the API-key option; the
// backend validates every request against the issuer's JWKS regardless of
// what this file claims, so nothing here is trusted, only convenient.

export interface OidcConfig {
  issuer: string;
  client_id: string;
}

interface OidcSession {
  access: string;
  refresh: string | null;
  /** Unix seconds; refreshed ahead of this. */
  exp: number;
  sub: string;
}

const SESSION_STORAGE = "sovereign-rag.oidc";
const FLIGHT_STORAGE = "sovereign-rag.oidc-flight"; // verifier+state across the redirect
const EXP_MARGIN_S = 30;

export async function fetchAuthConfig(): Promise<OidcConfig | null> {
  const response = await fetch("/api/auth/config");
  if (!response.ok) return null;
  const body = (await response.json()) as { oidc: OidcConfig | null };
  return body.oidc;
}

async function discover(issuer: string): Promise<{ authorize: string; token: string }> {
  const response = await fetch(`${issuer}/.well-known/openid-configuration`);
  if (!response.ok) throw new Error(`discovery failed: ${response.status}`);
  const doc = (await response.json()) as {
    authorization_endpoint: string;
    token_endpoint: string;
  };
  return { authorize: doc.authorization_endpoint, token: doc.token_endpoint };
}

function randomUrlSafe(bytes: number): string {
  const raw = crypto.getRandomValues(new Uint8Array(bytes));
  return btoa(String.fromCharCode(...raw))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

async function challengeS256(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

function decodeJwtPayload(token: string): { exp?: number; sub?: string } {
  const payload = token.split(".")[1] ?? "";
  const padded = payload.replaceAll("-", "+").replaceAll("_", "/");
  try {
    return JSON.parse(atob(padded)) as { exp?: number; sub?: string };
  } catch {
    return {};
  }
}

/** Kick off the redirect to the IdP's authorization endpoint. */
export async function beginLogin(config: OidcConfig): Promise<void> {
  const { authorize } = await discover(config.issuer);
  const verifier = randomUrlSafe(48);
  const state = randomUrlSafe(24);
  sessionStorage.setItem(FLIGHT_STORAGE, JSON.stringify({ verifier, state }));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id,
    redirect_uri: `${window.location.origin}/auth/callback`,
    scope: "openid profile",
    state,
    code_challenge: await challengeS256(verifier),
    code_challenge_method: "S256",
  });
  window.location.assign(`${authorize}?${params.toString()}`);
}

function storeTokens(body: { access_token: string; refresh_token?: string }): void {
  const claims = decodeJwtPayload(body.access_token);
  const session: OidcSession = {
    access: body.access_token,
    refresh: body.refresh_token ?? null,
    exp: claims.exp ?? 0,
    sub: claims.sub ?? "",
  };
  localStorage.setItem(SESSION_STORAGE, JSON.stringify(session));
}

let completeFlight: Promise<void> | null = null;

/** Finish the flow on /auth/callback; throws with a readable reason.

React StrictMode mounts effects twice in development: the exchange is
memoized per page load so the second run awaits the first instead of
finding the one-shot verifier already consumed. */
export function completeLogin(config: OidcConfig): Promise<void> {
  completeFlight ??= completeLoginOnce(config);
  return completeFlight;
}

async function completeLoginOnce(config: OidcConfig): Promise<void> {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const flightRaw = sessionStorage.getItem(FLIGHT_STORAGE);
  sessionStorage.removeItem(FLIGHT_STORAGE);
  if (code === null || state === null || flightRaw === null) {
    throw new Error("missing code, state or verifier");
  }
  const flight = JSON.parse(flightRaw) as { verifier: string; state: string };
  if (state !== flight.state) throw new Error("state mismatch");
  const { token } = await discover(config.issuer);
  const response = await fetch(token, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: `${window.location.origin}/auth/callback`,
      client_id: config.client_id,
      code_verifier: flight.verifier,
    }),
  });
  if (!response.ok) throw new Error(`token exchange failed: ${response.status}`);
  storeTokens((await response.json()) as { access_token: string; refresh_token?: string });
}

export function oidcSession(): OidcSession | null {
  const raw = localStorage.getItem(SESSION_STORAGE);
  if (raw === null) return null;
  try {
    return JSON.parse(raw) as OidcSession;
  } catch {
    return null;
  }
}

export function clearOidcSession(): void {
  localStorage.removeItem(SESSION_STORAGE);
}

/** A valid access token, refreshed if it is about to expire; null if none. */
export async function freshOidcToken(): Promise<string | null> {
  const session = oidcSession();
  if (session === null) return null;
  if (session.exp * 1000 - Date.now() > EXP_MARGIN_S * 1000) return session.access;
  if (session.refresh === null) {
    clearOidcSession();
    return null;
  }
  const config = await fetchAuthConfig();
  if (config === null) return null;
  const { token } = await discover(config.issuer);
  const response = await fetch(token, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: session.refresh,
      client_id: config.client_id,
    }),
  });
  if (!response.ok) {
    clearOidcSession();
    return null;
  }
  storeTokens((await response.json()) as { access_token: string; refresh_token?: string });
  return oidcSession()?.access ?? null;
}
