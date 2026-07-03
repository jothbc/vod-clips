import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { fetchSystemStatus, type SystemStatus } from "../../api/v2";

export type SystemIndicator = "ok" | "warn" | "error";

export function systemStatusIndicator(data: SystemStatus | null): SystemIndicator {
  if (!data) return "warn";
  if (!data.ffmpeg) return "error";
  if (data.whisper.configured_device === "cuda" && data.whisper.effective_device !== "cuda") return "warn";
  if (!data.ollama.available) return "warn";
  return "ok";
}

interface SystemStatusValue {
  data: SystemStatus | null;
  error: string | null;
  indicator: SystemIndicator;
}

const SystemStatusContext = createContext<SystemStatusValue | null>(null);

function useSystemStatusPolling(intervalMs = 5000): SystemStatusValue {
  const [data, setData] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const status = await fetchSystemStatus();
        if (!cancelled) {
          setData(status);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Erro ao carregar status");
        }
      }
    };
    load();
    const timer = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [intervalMs]);

  return { data, error, indicator: systemStatusIndicator(data) };
}

export function SystemStatusProvider({ children }: { children: ReactNode }) {
  const value = useSystemStatusPolling();
  return <SystemStatusContext.Provider value={value}>{children}</SystemStatusContext.Provider>;
}

export function useSystemStatus(): SystemStatusValue {
  const ctx = useContext(SystemStatusContext);
  if (!ctx) {
    throw new Error("useSystemStatus must be used within SystemStatusProvider");
  }
  return ctx;
}
