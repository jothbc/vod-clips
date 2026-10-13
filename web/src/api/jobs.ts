import { apiUrl } from "./base";

export interface JobState {
  id: string;
  status: string;
  video_path: string;
  output_dir: string;
  feature?: string;
  phase: string;
  current: number;
  total: number | null;
  message: string;
  percent: number;
  warnings: string[];
  error: string | null;
  highlight_count: number;
  clips_exported?: boolean;
  result_clip_id?: string | null;
  result_video_id?: string | null;
  log: string[];
  video_id?: string | null;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export async function fetchJobs(params: {
  status?: string;
  video_id?: string;
  limit?: number;
} = {}): Promise<{ jobs: JobState[] }> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.video_id) qs.set("video_id", params.video_id);
  if (params.limit != null) qs.set("limit", String(params.limit));
  const r = await fetch(apiUrl(`/api/v2/jobs?${qs}`));
  if (!r.ok) throw new Error("Failed to list jobs");
  return r.json();
}

export async function getV2Job(jobId: string): Promise<JobState> {
  const r = await fetch(apiUrl(`/api/v2/jobs/${encodeURIComponent(jobId)}`));
  if (!r.ok) throw new Error("Job not found");
  return r.json();
}

export async function cancelV2Job(jobId: string): Promise<void> {
  const r = await fetch(apiUrl(`/api/v2/jobs/${encodeURIComponent(jobId)}/cancel`), {
    method: "POST",
  });
  if (!r.ok && r.status !== 404) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || r.statusText);
  }
}

export function subscribeV2JobEvents(
  jobId: string,
  onUpdate: (state: JobState) => void,
  onError?: (err: Error) => void
): () => void {
  const es = new EventSource(apiUrl(`/api/v2/jobs/${encodeURIComponent(jobId)}/events`));
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let stopped = false;

  const isTerminal = (status: string) =>
    status === "completed" || status === "failed" || status === "cancelled";

  const poll = () => {
    getV2Job(jobId)
      .then((state) => {
        onUpdate(state);
        if (isTerminal(state.status)) stop();
      })
      .catch(() => {});
  };

  const stop = () => {
    if (stopped) return;
    stopped = true;
    es.close();
    if (pollTimer) clearInterval(pollTimer);
  };

  es.onmessage = (ev) => {
    try {
      onUpdate(JSON.parse(ev.data) as JobState);
    } catch (e) {
      onError?.(e instanceof Error ? e : new Error(String(e)));
    }
  };

  es.onerror = () => {
    if (!pollTimer) pollTimer = setInterval(poll, 1500);
    poll();
    onError?.(new Error("SSE connection error — polling job status"));
  };

  return stop;
}
