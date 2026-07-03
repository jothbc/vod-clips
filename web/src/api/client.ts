import { apiUrl } from "./base";

export type AnalysisMode = "auto" | "gaming" | "multimodal";

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
}

export interface FeatureInfo {
  id: string;
  label: string;
  description: string;
  enabled: boolean;
}

export interface EdlSpan {
  index: number;
  start: number;
  end: number;
  kind: "keep" | "cut";
  source: string;
  reason: string;
  text: string;
}

export interface EdlResponse {
  job_id: string;
  source_video_url: string;
  total_duration: number;
  kept_duration: number;
  cut_duration: number;
  llm_available: boolean;
  spans: EdlSpan[];
}

export interface FinalVideo {
  format: string;
  url: string;
  filename: string;
}

export interface FinalResponse {
  job_id: string;
  output_dir: string;
  videos: FinalVideo[];
}

export interface RenderJobBody {
  cut_indices?: number[];
  formats?: string[];
  use_nvenc?: boolean;
}

export interface CaptionWord {
  start: number;
  end: number;
  word: string;
}

export interface CaptionSegment {
  index: number;
  start: number;
  end: number;
  text: string;
  words: CaptionWord[];
}

export interface CaptionsResponse {
  job_id: string;
  source_video_url: string;
  font_id: string;
  style: string;
  segments: CaptionSegment[];
  segments_original: CaptionSegment[];
  warnings: string[];
}

export interface CaptionFont {
  id: string;
  label: string;
  filename: string;
  preview_url: string;
}

export interface CaptionedResponse {
  job_id: string;
  output_dir: string;
  url: string;
  filename: string;
}

export interface PublishItem {
  index: number;
  video_path: string;
  source_label: string;
  platform: string;
  title: string;
  description: string;
  tags: string[];
  thumbnail_timestamp: number;
  thumbnail_url: string | null;
}

export interface PublishResponse {
  job_id: string;
  output_dir: string;
  platform: string;
  content_type: "game" | "other";
  game_name: string;
  video_context: string;
  channel_info: string;
  items: PublishItem[];
  warnings: string[];
}

export type PublishContentType = "game" | "other";

export interface PublishJobParams {
  video_paths: string[];
  platform: "youtube" | "short_form";
  content_type: PublishContentType;
  game_name?: string;
  video_context?: string;
  channel_info?: string;
}

export interface SaveCaptionsBody {
  segments: CaptionSegment[];
  font_id?: string;
}

export interface RenderCaptionsBody {
  segments?: CaptionSegment[];
  font_id?: string;
  use_nvenc?: boolean;
  output_format?: "native" | "reels";
}

export interface UploadHandle {
  promise: Promise<{ path: string; filename: string; size_bytes: number }>;
  abort: () => void;
}

export interface StoredVod {
  path: string;
  filename: string;
  size_bytes: number;
  modified: number;
}

export interface StoredVodsResponse {
  dir: string;
  vods: StoredVod[];
}

export interface HighlightItem {
  index: number;
  title: string;
  score: number;
  start: number;
  end: number;
  source: string;
  reason: string;
}

export interface ResolutionPreset {
  id: string;
  label: string;
  width: number;
  height: number;
}

export interface HighlightsResponse {
  job_id: string;
  source_video_url: string;
  highlights: HighlightItem[];
  preview_size_bytes?: number;
  preview_is_full_source?: boolean;
  source_width?: number;
  source_height?: number;
  youtube_presets?: ResolutionPreset[];
  reels_presets?: ResolutionPreset[];
  default_youtube?: ResolutionPreset;
  default_reels?: ResolutionPreset;
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
  youtube_filename?: string | null;
  reels_filename?: string | null;
}

export interface ExportedReelJob {
  job_id: string;
  output_dir: string;
  source_video: string;
  modified: number;
  clip_count: number;
  clips: ClipItem[];
}

export interface ReelsLibraryResponse {
  dir: string;
  jobs: ExportedReelJob[];
}

export interface PickableReelClip {
  path: string;
  title: string;
  format: "youtube" | "reels" | string;
  job_id: string;
  source_video: string;
  clip_index: number;
  size_bytes: number;
  modified: number;
}

export interface PickableReelsResponse {
  dir: string;
  clips: PickableReelClip[];
}

export interface CreateJobBody {
  video_path: string;
  /** Which workflow to run: reels | cleanup */
  feature?: string;
  preset?: string;
  mode?: AnalysisMode;
  max_clips?: number;
  use_nvenc?: boolean;
  cleanup?: boolean;
  resume?: boolean;
  /** Legacy: export all highlights immediately after analysis */
  export_clips?: boolean;
  /** Extra feature-specific params */
  params?: Record<string, unknown>;
  /** Prior job to cancel/cleanup when starting a new analysis */
  previous_job_id?: string | null;
}

export interface ResetSessionBody {
  previous_job_id?: string | null;
  cleanup_previous?: boolean;
}

export interface ExportResolution {
  width: number;
  height: number;
}

export interface ExportJobBody {
  highlight_indices: number[];
  use_nvenc?: boolean;
  youtube_resolution?: ExportResolution;
  reels_resolution?: ExportResolution;
}

export interface TwitchDownloadState {
  id: string;
  url: string;
  video_id?: string;
  status: string;
  percent: number;
  message: string;
  path: string;
  filename: string;
  size_bytes: number;
  error: string | null;
  queue_position?: number;
  created_at?: string;
  updated_at?: string;
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
  onProgress: (loaded: number, total: number | null) => void
): UploadHandle {
  const xhr = new XMLHttpRequest();
  let aborted = false;

  const promise = new Promise<{ path: string; filename: string; size_bytes: number }>(
    (resolve, reject) => {
      const form = new FormData();
      form.append("file", file);

      xhr.upload.addEventListener("progress", (e) => {
        const total = e.lengthComputable ? e.total : file.size;
        onProgress(e.loaded, total > 0 ? total : null);
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

      xhr.addEventListener("abort", () => reject(new Error("Upload cancelado")));
      xhr.addEventListener("error", () =>
        reject(
          new Error(
            "Upload network error — check VITE_API_BASE in web/.env.local matches your reels serve --port."
          )
        )
      );
      xhr.addEventListener("timeout", () => reject(new Error("Upload timed out")));
      xhr.timeout = 0;
      xhr.open("POST", apiUrl("/api/upload"));
      xhr.send(form);
    }
  );

  return {
    promise,
    abort: () => {
      if (!aborted) {
        aborted = true;
        xhr.abort();
      }
    },
  };
}

/** List .mp4 files already sitting in temp/vods on the server. */
export async function fetchStoredVods(): Promise<StoredVodsResponse> {
  const r = await fetch(apiUrl("/api/vods"));
  if (!r.ok) throw new Error("Failed to list VODs");
  return r.json();
}

/** Delete one stored VOD from temp/vods. */
export async function deleteStoredVod(path: string): Promise<{ deleted: boolean; bytes_freed: number }> {
  const r = await fetch(apiUrl(`/api/vods?path=${encodeURIComponent(path)}`), {
    method: "DELETE",
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function clearJobStorage(jobId: string): Promise<CleanupResult> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/clear`), { method: "POST" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function fetchHealth(): Promise<{ ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean }> {
  const r = await fetch(apiUrl("/api/health"));
  if (!r.ok) throw new Error("Health check failed");
  return r.json();
}

export async function startTwitchDownload(url: string): Promise<{ download_id: string }> {
  const r = await fetch(apiUrl("/api/twitch/download"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url.trim() }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function startTwitchDownloadBatch(
  urls: string[]
): Promise<{ download_ids: string[]; downloads: TwitchDownloadState[] }> {
  const r = await fetch(apiUrl("/api/twitch/download/batch"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function fetchTwitchDownloads(): Promise<{ downloads: TwitchDownloadState[] }> {
  const r = await fetch(apiUrl("/api/twitch/downloads"));
  if (!r.ok) throw new Error("Failed to list downloads");
  return r.json();
}

export async function cancelTwitchDownload(
  downloadId: string
): Promise<{ download_id: string; status: string }> {
  const r = await fetch(apiUrl(`/api/twitch/download/${downloadId}/cancel`), {
    method: "POST",
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function getTwitchDownload(downloadId: string): Promise<TwitchDownloadState> {
  const r = await fetch(apiUrl(`/api/twitch/download/${downloadId}`));
  if (!r.ok) throw new Error("Download not found");
  return r.json();
}

export function subscribeTwitchDownloadEvents(
  downloadId: string,
  onUpdate: (state: TwitchDownloadState) => void,
  onError?: (err: Error) => void
): () => void {
  const es = new EventSource(apiUrl(`/api/twitch/download/${downloadId}/events`));

  es.onmessage = (ev) => {
    try {
      onUpdate(JSON.parse(ev.data) as TwitchDownloadState);
    } catch (e) {
      onError?.(e instanceof Error ? e : new Error(String(e)));
    }
  };

  es.onerror = () => {
    getTwitchDownload(downloadId)
      .then(onUpdate)
      .catch(() => {});
    onError?.(new Error("SSE connection error"));
  };

  return () => es.close();
}

export async function resetSession(body: ResetSessionBody = {}): Promise<void> {
  const r = await fetch(apiUrl("/api/session/reset"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      previous_job_id: body.previous_job_id ?? null,
      cleanup_previous: body.cleanup_previous ?? true,
    }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
}

export async function createJob(body: CreateJobBody): Promise<{ job_id: string }> {
  const r = await fetch(apiUrl("/api/jobs"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function getJob(jobId: string): Promise<JobState> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}`));
  if (!r.ok) throw new Error("Job not found");
  return r.json();
}

export async function cancelJob(jobId: string): Promise<void> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/cancel`), { method: "POST" });
  if (!r.ok && r.status !== 404) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || r.statusText);
  }
}

export async function fetchFeatures(): Promise<FeatureInfo[]> {
  const r = await fetch(apiUrl("/api/features"));
  if (!r.ok) throw new Error("Failed to load features");
  const data = await r.json();
  return data.features as FeatureInfo[];
}

export async function fetchEdl(jobId: string): Promise<EdlResponse> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/edl`));
  if (!r.ok) throw new Error("EDL not ready");
  return r.json();
}

export async function renderCleanup(
  jobId: string,
  body: RenderJobBody
): Promise<{ job_id: string; status: string }> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/render`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function fetchFinal(jobId: string): Promise<FinalResponse> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/final`));
  if (!r.ok) throw new Error("Final video not ready");
  return r.json();
}

export async function fetchCaptionFonts(): Promise<{ fonts: CaptionFont[] }> {
  const r = await fetch(apiUrl("/api/captions/fonts"));
  if (!r.ok) throw new Error("Failed to load caption fonts");
  return r.json();
}

export async function fetchCaptions(jobId: string): Promise<CaptionsResponse> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/captions`));
  if (!r.ok) throw new Error("Captions not ready");
  return r.json();
}

export async function saveCaptions(jobId: string, body: SaveCaptionsBody): Promise<CaptionsResponse> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/captions`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function renderCaptions(
  jobId: string,
  body: RenderCaptionsBody
): Promise<{ job_id: string; status: string }> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/render-captions`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function fetchCaptioned(jobId: string): Promise<CaptionedResponse> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/captioned`));
  if (!r.ok) throw new Error("Captioned video not ready");
  return r.json();
}

export async function fetchPublish(jobId: string): Promise<PublishResponse> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/publish`));
  if (!r.ok) throw new Error("Publish metadata not ready");
  return r.json();
}

export async function fetchClips(jobId: string): Promise<{ clips: ClipItem[]; output_dir: string }> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/clips`));
  if (!r.ok) throw new Error("Clips not ready");
  return r.json();
}

export async function fetchReelsLibrary(): Promise<ReelsLibraryResponse> {
  const r = await fetch(apiUrl("/api/reels/library"));
  if (!r.ok) throw new Error("Failed to load reels library");
  return r.json();
}

export async function fetchPickableReelClips(): Promise<PickableReelsResponse> {
  const r = await fetch(apiUrl("/api/reels/pickable-clips"));
  if (!r.ok) throw new Error("Failed to load exported clips");
  return r.json();
}

export async function deleteReelJob(jobId: string): Promise<{ deleted: boolean; bytes_freed: number }> {
  const r = await fetch(apiUrl(`/api/reels/library/${encodeURIComponent(jobId)}`), {
    method: "DELETE",
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export async function fetchHighlights(jobId: string): Promise<HighlightsResponse> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/highlights`));
  if (!r.ok) throw new Error("Highlights not ready");
  return r.json();
}

export async function exportHighlights(jobId: string, body: ExportJobBody): Promise<{ job_id: string; status: string }> {
  const r = await fetch(apiUrl(`/api/jobs/${jobId}/export`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

export function subscribeJobEvents(
  jobId: string,
  onUpdate: (state: JobState) => void,
  onError?: (err: Error) => void
): () => void {
  const es = new EventSource(apiUrl(`/api/jobs/${jobId}/events`));
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let stopped = false;

  const poll = () => {
    getJob(jobId)
      .then((state) => {
        onUpdate(state);
        if (state.status === "completed" || state.status === "failed") {
          stop();
        }
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
