import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { fetchJobs, type JobState } from "../../api/jobs";

const ACTIVE_STATUSES = new Set(["queued", "running", "awaiting_review"]);
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const SEEN_KEY = "reels.jobs.seen_terminal";

interface JobContextValue {
  jobs: JobState[];
  activeJobs: JobState[];
  /** True while a queued/running job exists for the given video (and optional feature). */
  hasActiveJob: (videoId?: string | null, feature?: string) => boolean;
  refresh: () => void;
}

const JobContext = createContext<JobContextValue | null>(null);

export function useJobs(): JobContextValue {
  const ctx = useContext(JobContext);
  if (!ctx) throw new Error("useJobs must be used within JobProvider");
  return ctx;
}

interface Toast {
  key: string;
  job: JobState;
}

function loadSeen(): Set<string> {
  try {
    const raw = sessionStorage.getItem(SEEN_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function persistSeen(seen: Set<string>) {
  try {
    sessionStorage.setItem(SEEN_KEY, JSON.stringify([...seen]));
  } catch {
    /* ignore */
  }
}

function jobLabel(feature?: string): string {
  switch (feature) {
    case "v2_analyze":
      return "Análise de destaques";
    case "v2_export_clips":
      return "Geração de clips";
    case "v2_captions":
      return "Legendas";
    case "v2_cleanup":
      return "Remoção de silêncios";
    case "v2_trim":
      return "Recorte";
    default:
      return feature ?? "Job";
  }
}

function jobWatchTarget(job: JobState): string | null {
  const target = job.result_video_id || job.video_id;
  return target ? `/watch/${encodeURIComponent(target)}` : null;
}

export function JobProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<JobState[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seenRef = useRef<Set<string>>(loadSeen());
  const firstLoadRef = useRef(true);
  const tickRef = useRef(0);

  const pushToast = useCallback((job: JobState) => {
    const key = `${job.id}:${Date.now()}`;
    setToasts((prev) => [...prev, { key, job }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.key !== key));
    }, 9000);
  }, []);

  const applyJobs = useCallback(
    (next: JobState[]) => {
      const seen = seenRef.current;
      for (const job of next) {
        if (!TERMINAL_STATUSES.has(job.status)) continue;
        if (seen.has(job.id)) continue;
        seen.add(job.id);
        if (!firstLoadRef.current && job.status !== "cancelled") {
          pushToast(job);
        }
      }
      persistSeen(seen);
      firstLoadRef.current = false;
      setJobs(next);
    },
    [pushToast]
  );

  const refresh = useCallback(() => {
    fetchJobs({ limit: 50 })
      .then((data) => applyJobs(data.jobs))
      .catch(() => {});
  }, [applyJobs]);

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      fetchJobs({ limit: 50 })
        .then((data) => {
          if (!cancelled) applyJobs(data.jobs);
        })
        .catch(() => {});
    };
    poll();
    const timer = window.setInterval(() => {
      tickRef.current += 1;
      poll();
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [applyJobs]);

  const hasActiveJob = useCallback(
    (videoId?: string | null, feature?: string) =>
      jobs.some(
        (j) =>
          ACTIVE_STATUSES.has(j.status) &&
          (!videoId || j.video_id === videoId) &&
          (!feature || j.feature === feature)
      ),
    [jobs]
  );

  const activeJobs = jobs.filter((j) => ACTIVE_STATUSES.has(j.status));

  const dismiss = useCallback((key: string) => {
    setToasts((prev) => prev.filter((t) => t.key !== key));
  }, []);

  return (
    <JobContext.Provider value={{ jobs, activeJobs, hasActiveJob, refresh }}>
      {children}
      {toasts.length > 0 && (
        <div className="v2-toast-stack" role="status" aria-live="polite">
          {toasts.map(({ key, job }) => {
            const target = job.status === "completed" ? jobWatchTarget(job) : null;
            return (
              <div key={key} className={`v2-toast v2-toast--${job.status}`}>
                <div className="v2-toast-body">
                  <strong>{jobLabel(job.feature)}</strong>
                  <span>
                    {job.status === "completed" ? "concluído" : "falhou"}
                    {job.error ? ` — ${job.error}` : ""}
                  </span>
                  {target && (
                    <Link to={target} className="v2-toast-link" onClick={() => dismiss(key)}>
                      Ver vídeo
                    </Link>
                  )}
                </div>
                <button
                  type="button"
                  className="v2-toast-close"
                  aria-label="Fechar notificação"
                  onClick={() => dismiss(key)}
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>
      )}
    </JobContext.Provider>
  );
}
