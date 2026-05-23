export type AnalysisMode = "auto" | "gaming" | "multimodal";

export interface JobState {
  id: string;
  status: string;
  video_path: string;
  output_dir: string;
  phase: string;
  current: number;
  total: number | null;
  message: string;
  percent: number;
  warnings: string[];
  error: string | null;
  highlight_count: number;
  log: string[];
}

export interface ClipItem {
  index: number;
  title: string;
  score: number;
  start: number;
  end: number;
  source: string;
  youtube_url: string | null;
  reels_url: string | null;
}

export interface CreateJobBody {
  video_path: string;
  preset?: string;
  mode?: AnalysisMode;
  max_clips?: number;
  use_nvenc?: boolean;
  cleanup?: boolean;
  resume?: boolean;
}

export interface CleanupResult {
  vod_deleted: boolean;
  output_deleted: boolean;
  bytes_freed: number;
  already_cleaned: boolean;
}

export function formatBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

export function uploadVodWithProgress(
  file: File,
  onProgress: (percent: number) => void
): Promise<{ path: string; filename: string; size_bytes: number }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress((e.loaded / e.total) * 100);
    });

    xhr.addEventListener("load", () => {
      let data: { detail?: string; path?: string; filename?: string; size_bytes?: number } = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300 && data.path) {
        resolve({
          path: data.path,
          filename: data.filename ?? file.name,
          size_bytes: data.size_bytes ?? file.size,
        });
      } else {
        reject(new Error(data.detail || xhr.statusText || "Upload failed"));
      }
    });

    xhr.addEventListener("error", () => reject(new Error("Upload network error")));
    xhr.open("POST", "/api/upload");
    xhr.send(form);
  });
}

export async function clearJobStorage(jobId: string): Promise<CleanupResult> {
  const r = await fetch(`/api/jobs/${jobId}/clear`, { method: "POST" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function fetchHealth(): Promise<{ ffmpeg: boolean; ollama: boolean }> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error("Health check failed");
  return r.json();
}

export async function createJob(body: CreateJobBody): Promise<{ job_id: string }> {
  const r = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function getJob(jobId: string): Promise<JobState> {
  const r = await fetch(`/api/jobs/${jobId}`);
  if (!r.ok) throw new Error("Job not found");
  return r.json();
}

export async function fetchClips(jobId: string): Promise<{ clips: ClipItem[]; output_dir: string }> {
  const r = await fetch(`/api/jobs/${jobId}/clips`);
  if (!r.ok) throw new Error("Clips not ready");
  return r.json();
}

export function subscribeJobEvents(
  jobId: string,
  onUpdate: (state: JobState) => void,
  onError?: (err: Error) => void
): () => void {
  const es = new EventSource(`/api/jobs/${jobId}/events`);

  es.onmessage = (ev) => {
    try {
      onUpdate(JSON.parse(ev.data) as JobState);
    } catch (e) {
      onError?.(e instanceof Error ? e : new Error(String(e)));
    }
  };

  es.onerror = () => {
    onError?.(new Error("SSE connection error"));
    es.close();
  };

  return () => es.close();
}
