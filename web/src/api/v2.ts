import { apiUrl } from "./base";

export interface VideoSummary {
  id: string;
  title: string;
  kind: "original" | "clip";
  duration: number;
  width: number;
  height: number;
  stream_url: string;
  thumbnail_url?: string;
  has_transcript: boolean;
  clip_count: number;
  parent_id?: string;
  format?: string;
  start?: number;
  end?: number;
  formats?: string[];
  uploaded_at?: string;
}

export interface ClipSummary {
  id: string;
  parent_id: string;
  title: string;
  format: string;
  formats?: string[];
  duration: number;
  duration_label: string;
  stream_url: string;
  thumbnail_url?: string;
}

export interface VideoDetail extends VideoSummary {
  source_path: string;
  fps: number;
  size_bytes: number;
  parent_slug?: string;
  clip_slug?: string;
  stream_urls?: Record<string, string>;
  source_feature?: string;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface TranscriptResponse {
  video_id: string;
  segments: TranscriptSegment[];
  segments_original: TranscriptSegment[];
}

export interface GalleryVideo {
  id: string;
  title: string;
  kind: "original" | "clip";
  stream_url: string;
  clip_count: number;
  clips: GalleryClip[];
}

export interface GalleryClip {
  id: string;
  clip_slug: string;
  title: string;
  formats: string[];
  stream_urls: Record<string, string>;
}

export interface MetadataJobResponse {
  video_id: string;
  job_id?: string;
  status: string;
  has_transcript: boolean;
}

export interface HighlightItem {
  index: number;
  start: number;
  end: number;
  title: string;
  score: number;
  reason: string;
}

export interface HighlightsResponse {
  video_id: string;
  source_width?: number;
  source_height?: number;
  youtube_presets?: ResolutionPreset[];
  reels_presets?: ResolutionPreset[];
  default_youtube?: ResolutionPreset;
  default_reels?: ResolutionPreset;
  highlights: HighlightItem[];
}

export interface ResolutionPreset {
  id: string;
  label: string;
  width: number;
  height: number;
}

export interface GenerateClipSelection {
  index: number;
  start: number;
  end: number;
  title: string;
  export_youtube: boolean;
  export_reels: boolean;
  burn_captions: boolean;
  cleanup_silence: boolean;
}

export interface AnalyzeHighlightsBody {
  max_clips?: number;
}

export interface GenerateClipsBody {
  selections: GenerateClipSelection[];
  max_clips?: number;
  pre_pad_seconds?: number;
  post_pad_seconds?: number;
  min_duration?: number;
  use_nvenc?: boolean;
}

export interface JobStartResponse {
  video_id: string;
  job_id: string;
  status: string;
}

export interface CaptionsConfigResponse {
  defaults: Record<string, unknown>;
  fonts: { id: string; label: string }[];
}

export interface CleanupConfigResponse {
  defaults: Record<string, unknown>;
}

export interface CaptionsJobBody {
  font_id?: string;
  max_words_per_line?: number;
  word_gap_seconds?: number;
  bottom_margin_ratio?: number;
  font_size_ratio?: number;
  primary_colour?: string;
  highlight_colour?: string;
  output_format?: "reels" | "youtube" | "both";
  source_format?: "reels" | "youtube";
  use_nvenc?: boolean;
}

export interface CleanupJobBody {
  min_gap_seconds?: number;
  pad_seconds?: number;
  use_silencedetect?: boolean;
  silence_noise_db?: number;
  remove_fillers?: boolean;
  use_llm?: boolean;
  export_youtube?: boolean;
  export_reels?: boolean;
  source_format?: "reels" | "youtube";
  use_nvenc?: boolean;
}

export interface CleanupEdlSpan {
  index: number;
  start: number;
  end: number;
  kind: "keep" | "cut";
  source: string;
  reason: string;
  text: string;
}

export interface CleanupEdlResponse {
  job_id: string;
  total_duration: number;
  kept_duration: number;
  cut_duration: number;
  llm_available: boolean;
  spans: CleanupEdlSpan[];
}

export interface CleanupRenderBody {
  cut_indices: number[];
  export_youtube?: boolean;
  export_reels?: boolean;
  use_nvenc?: boolean;
}

export interface TrimJobBody {
  keep_spans: [number, number][];
  source_format?: "reels" | "youtube";
  use_nvenc?: boolean;
}

export interface SystemStatus {
  ffmpeg: boolean;
  yt_dlp: boolean;
  ollama: {
    available: boolean;
    host: string;
    vision_model: string;
    merge_model: string;
  };
  whisper: {
    configured_device: string;
    effective_device: string;
    model: string;
    compute_type: string;
  };
  cuda: {
    libs_available: boolean;
    nvenc_available: boolean;
  };
  gpu: {
    name: string;
    memory_total_mb: number;
    memory_used_mb: number;
    utilization_percent: number | null;
  } | null;
  cpu: { percent: number; count: number } | null;
  memory: { total_mb: number; used_mb: number; percent: number } | null;
  metrics_partial: boolean;
  active_job: {
    id: string;
    feature: string;
    phase: string;
    percent: number;
    message: string;
    status: string;
  } | null;
  preset: string;
}

export interface VideosListResponse {
  videos: VideoSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface ClipsListResponse {
  clips: ClipSummary[];
}

async function v2Fetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), init);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface SearchResponse {
  query: string;
  videos: VideoSummary[];
  total: number;
}

export function fetchVideos(offset = 0, limit = 24): Promise<VideosListResponse> {
  return v2Fetch(`/api/v2/videos?offset=${offset}&limit=${limit}`);
}

export function searchVideos(q: string, limit = 24): Promise<SearchResponse> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  return v2Fetch(`/api/v2/search?${params}`);
}

export function fetchClips(limit = 12): Promise<ClipsListResponse> {
  return v2Fetch(`/api/v2/clips?limit=${limit}`);
}

export function fetchVideo(id: string): Promise<VideoDetail> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}`);
}

export function fetchRelated(id: string): Promise<{ items: VideoSummary[] }> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/related`);
}

export function fetchGallery(): Promise<{ videos: GalleryVideo[] }> {
  return v2Fetch("/api/v2/gallery");
}

export function deleteVideo(id: string): Promise<{ deleted: boolean; video_id: string; bytes_freed: number }> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function postMetadata(id: string): Promise<MetadataJobResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/metadata`, { method: "POST" });
}

export function fetchTranscript(id: string): Promise<TranscriptResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/transcript`);
}

export function putTranscript(id: string, segments: TranscriptSegment[]): Promise<TranscriptResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/transcript`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ segments }),
  });
}

export function fetchSystemStatus(): Promise<SystemStatus> {
  return v2Fetch("/api/v2/system");
}

export function postAnalyzeHighlights(id: string, body: AnalyzeHighlightsBody = {}): Promise<JobStartResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/analyze-highlights`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_clips: body.max_clips ?? 15 }),
  });
}

export function fetchHighlights(id: string): Promise<HighlightsResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/highlights`);
}

export function postGenerateClips(id: string, body: GenerateClipsBody): Promise<JobStartResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/generate-clips`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postCleanup(id: string, body: CleanupJobBody = {}): Promise<JobStartResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/cleanup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postCaptions(id: string, body: CaptionsJobBody = {}): Promise<JobStartResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/captions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postTrim(id: string, body: TrimJobBody): Promise<JobStartResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/trim`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postTrimFinalize(
  jobId: string,
  mode: "new_vod" | "replace"
): Promise<{ job_id: string; mode: string; video_id: string }> {
  return v2Fetch(`/api/v2/jobs/${encodeURIComponent(jobId)}/trim/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

export function trimPreviewUrl(jobId: string): string {
  return apiUrl(`/api/v2/jobs/${encodeURIComponent(jobId)}/trim/preview`);
}

export function fetchCaptionsConfig(): Promise<CaptionsConfigResponse> {
  return v2Fetch("/api/v2/config/captions");
}

export function fetchCleanupConfig(): Promise<CleanupConfigResponse> {
  return v2Fetch("/api/v2/config/cleanup");
}

export function fetchCleanupEdl(jobId: string): Promise<CleanupEdlResponse> {
  return v2Fetch(`/api/v2/jobs/${encodeURIComponent(jobId)}/cleanup/edl`);
}

export function postCleanupRender(jobId: string, body: CleanupRenderBody): Promise<JobStartResponse> {
  return v2Fetch(`/api/v2/jobs/${encodeURIComponent(jobId)}/cleanup/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postPublish(id: string, body: Record<string, unknown> = {}): Promise<{ job_id: string }> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function uploadVideoV2(
  file: File,
  onProgress?: (loaded: number, total: number) => void
): Promise<{ video_id: string; filename: string; size_bytes: number }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    xhr.open("POST", apiUrl("/api/upload"));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded, e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(xhr.responseText || `Upload failed (${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error("Upload network error"));
    xhr.send(form);
  });
}
