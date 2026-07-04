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
  webcam_region?: WebcamRegion | null;
  webcam_region_resolved?: WebcamRegion | null;
  webcam_eligible?: boolean;
  has_webcam_region?: boolean;
}

export interface WebcamRegion {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  source_width: number;
  source_height: number;
  frame_at: number;
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
  include_webcam: boolean;
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
    if (detail.startsWith("{")) {
      try {
        const parsed = JSON.parse(detail) as { detail?: string | { msg?: string }[] };
        if (typeof parsed.detail === "string") throw new Error(parsed.detail);
        if (Array.isArray(parsed.detail)) {
          const msg = parsed.detail.map((d) => d.msg).filter(Boolean).join("; ");
          if (msg) throw new Error(msg);
        }
      } catch (e) {
        if (e instanceof Error && !e.message.startsWith("{")) throw e;
      }
    }
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
  mode: "new_vod" | "replace" | "new_clip"
): Promise<{ job_id: string; mode: string; video_id: string }> {
  return v2Fetch(`/api/v2/jobs/${encodeURIComponent(jobId)}/trim/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

export function postTransformReel(
  id: string,
  body: { use_nvenc?: boolean; include_webcam?: boolean } = {}
): Promise<JobStartResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/transform-reel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function videoFrameUrl(id: string, at: number, cacheKey?: number): string {
  let url = `/api/v2/videos/${encodeURIComponent(id)}/frame?at=${encodeURIComponent(String(at))}`;
  if (cacheKey != null) url += `&_=${cacheKey}`;
  return apiUrl(url);
}

export function saveWebcamRegion(
  id: string,
  body: { x1: number; y1: number; x2: number; y2: number; frame_at?: number }
): Promise<{ webcam_region: WebcamRegion }> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/webcam-region`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function clearWebcamRegion(id: string): Promise<{ cleared: boolean }> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/webcam-region`, { method: "DELETE" });
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

export function postPublish(id: string, body: PublishJobBody = {}): Promise<JobStartResponse> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function createPublishSession(
  id: string,
  body: { source_format?: "reels" | "youtube" } = {}
): Promise<{ session_id: string; video_id: string }> {
  return v2Fetch(`/api/v2/videos/${encodeURIComponent(id)}/publish/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export type PublishSuggestField = "title" | "description" | "tags" | "thumbnail";

export interface PublishSuggestBody {
  field: PublishSuggestField;
  platform?: "youtube" | "short_form";
  content_type?: "game" | "other";
  game_name?: string;
  video_context?: string;
  channel_info?: string;
  title?: string;
}

export interface PublishSuggestResponse {
  field: PublishSuggestField;
  title?: string;
  description?: string;
  tags?: string[];
  thumbnail_second?: number;
  thumbnail_url?: string;
}

export function suggestPublishField(
  sessionId: string,
  body: PublishSuggestBody
): Promise<PublishSuggestResponse> {
  return v2Fetch(`/api/v2/publish/sessions/${encodeURIComponent(sessionId)}/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function savePublishDraft(
  sessionId: string,
  body: {
    title: string;
    description: string;
    tags: string[];
    platform?: "youtube" | "short_form";
  }
): Promise<{ session_id: string; ok: boolean }> {
  return v2Fetch(`/api/v2/publish/sessions/${encodeURIComponent(sessionId)}/draft`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function publishSessionThumbnailUrl(sessionId: string): string {
  return apiUrl(`/api/v2/publish/sessions/${encodeURIComponent(sessionId)}/thumbnail`);
}

export async function uploadSessionThumbnail(
  sessionId: string,
  file: File
): Promise<{ session_id: string; thumbnail_url: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    apiUrl(`/api/v2/publish/sessions/${encodeURIComponent(sessionId)}/thumbnail`),
    { method: "POST", body: form }
  );
  if (!res.ok) {
    const detail = await res.text();
    if (detail.startsWith("{")) {
      try {
        const parsed = JSON.parse(detail) as { detail?: string };
        if (typeof parsed.detail === "string") throw new Error(parsed.detail);
      } catch (e) {
        if (e instanceof Error && !e.message.startsWith("{")) throw e;
      }
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<{ session_id: string; thumbnail_url: string }>;
}

export interface PublishUploadCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface PublishTestUploadResponse {
  ok: boolean;
  platform?: string;
  checks: PublishUploadCheck[];
  channel_title?: string;
  channel_id?: string;
}

export function testPublishUpload(targetId: string): Promise<PublishTestUploadResponse> {
  return v2Fetch(`/api/v2/publish/targets/${encodeURIComponent(targetId)}/test-upload`, {
    method: "POST",
  });
}

export interface PublishJobBody {
  platform?: "youtube" | "short_form";
  content_type?: "game" | "other";
  game_name?: string;
  video_context?: string;
  channel_info?: string;
  source_format?: "reels" | "youtube";
  preset?: string;
  use_nvenc?: boolean;
}

export interface PublishItemResponse {
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
  items: PublishItemResponse[];
  warnings: string[];
}

export function fetchPublishJob(jobId: string): Promise<PublishResponse> {
  return v2Fetch(`/api/v2/jobs/${encodeURIComponent(jobId)}/publish`);
}

export function publishThumbnailUrl(jobId: string, index: number): string {
  return apiUrl(`/api/v2/jobs/${encodeURIComponent(jobId)}/publish/${index}/thumbnail`);
}

export type PublishPlatform = "youtube" | "instagram" | "tiktok";

export interface PublishTarget {
  id: string;
  label: string;
  platform: PublishPlatform;
  enabled: boolean;
  config: Record<string, unknown>;
  connected: boolean;
  oauth_configured: boolean;
  account_label: string;
  account_id: string;
  created_at: string;
  updated_at: string;
}

export function fetchPublishOAuthDefaults(): Promise<{
  redirect_uris: Record<PublishPlatform, string>;
}> {
  return v2Fetch("/api/v2/publish/oauth/defaults");
}

export function fetchPublishTargets(): Promise<{ targets: PublishTarget[] }> {
  return v2Fetch("/api/v2/publish/targets");
}

export function createPublishTarget(body: {
  label: string;
  platform: PublishPlatform;
  config?: Record<string, unknown>;
}): Promise<PublishTarget> {
  return v2Fetch("/api/v2/publish/targets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updatePublishTarget(
  id: string,
  body: Partial<{ label: string; enabled: boolean; config: Record<string, unknown> }>
): Promise<PublishTarget> {
  return v2Fetch(`/api/v2/publish/targets/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deletePublishTarget(id: string): Promise<void> {
  return v2Fetch(`/api/v2/publish/targets/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function startPublishTargetAuth(id: string): Promise<{ auth_url: string }> {
  return v2Fetch(`/api/v2/publish/targets/${encodeURIComponent(id)}/auth/start`);
}

export function disconnectPublishTarget(id: string): Promise<PublishTarget> {
  return v2Fetch(`/api/v2/publish/targets/${encodeURIComponent(id)}/disconnect`, { method: "POST" });
}

export type PublishDeployStatus = {
  deploy_id: string;
  status: "running" | "completed" | "failed";
  phase: string;
  percent: number;
  message: string;
  platform_post_id?: string;
  watch_url?: string;
  error?: string;
};

export function deployPublish(body: {
  job_id?: string;
  session_id?: string;
  target_id: string;
  item_index?: number;
  overrides?: Record<string, unknown>;
}): Promise<PublishDeployStatus> {
  return v2Fetch("/api/v2/publish/deploy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function fetchPublishDeploy(deployId: string): Promise<PublishDeployStatus> {
  return v2Fetch(`/api/v2/publish/deploy/${encodeURIComponent(deployId)}`);
}

export async function waitPublishDeploy(
  deployId: string,
  onUpdate?: (status: PublishDeployStatus) => void
): Promise<PublishDeployStatus> {
  for (;;) {
    const status = await fetchPublishDeploy(deployId);
    onUpdate?.(status);
    if (status.status === "completed" || status.status === "failed") {
      return status;
    }
    await new Promise((r) => setTimeout(r, 400));
  }
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
