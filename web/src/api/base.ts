/** API origin — set VITE_API_BASE in web/.env.local if your server is not on :8000. */

export function getApiBase(): string {
  const fromEnv = import.meta.env.VITE_API_BASE as string | undefined;
  if (fromEnv?.trim()) return fromEnv.trim().replace(/\/$/, "");
  // Same origin: Vite dev proxy (target from vite.config) or reels serve production bundle
  return "";
}

/** Human-readable target for UI hints. */
export function getApiDisplayLabel(): string {
  const base = getApiBase();
  if (base) return base;
  const proxyTarget =
    (import.meta.env.VITE_API_PROXY_TARGET as string | undefined)?.trim() ||
    "http://127.0.0.1:8000";
  return `${proxyTarget} (via Vite proxy)`;
}

export function apiUrl(path: string): string {
  const base = getApiBase();
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

const READY_MAX_ATTEMPTS = 40;
const READY_INTERVAL_MS = 250;

/** Wait until the Python API accepts requests (avoids 0% upload on cold start). */
export async function waitForApi(): Promise<void> {
  const label = getApiDisplayLabel();
  let lastError: Error | null = null;
  for (let i = 0; i < READY_MAX_ATTEMPTS; i++) {
    try {
      const r = await fetch(apiUrl("/api/ready"), { cache: "no-store" });
      if (r.ok) return;
      lastError = new Error(`API not ready (${r.status})`);
    } catch (e) {
      lastError = e instanceof Error ? e : new Error(String(e));
    }
    await new Promise((resolve) => setTimeout(resolve, READY_INTERVAL_MS));
  }
  throw (
    lastError ??
    new Error(
      `API not reachable at ${label}. Set VITE_API_BASE in web/.env.local to match reels serve --port.`
    )
  );
}
