import { useCallback, useEffect, useState } from "react";
import {
  exportHighlights,
  fetchClips,
  fetchHighlights,
  type ClipItem,
  type HighlightItem,
  type JobState,
  type ResolutionPreset,
} from "../api/client";
import ClipsGallery from "../components/ClipsGallery";
import CleanupPanel from "../components/CleanupPanel";
import ExportResolutionPicker from "../components/ExportResolutionPicker";
import HighlightsReview from "../components/HighlightsReview";
import JobForm, { type JobFormValues } from "../components/JobForm";
import ProgressPanel from "../components/ProgressPanel";
import { useJobController } from "../hooks/useJobController";

interface Props {
  apiReady: boolean;
  health: { ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null;
  consumePendingVod?: () => string | null;
  onOpenLibrary?: () => void;
}

const defaultForm: JobFormValues = {
  videoPath: "",
  mode: "gaming",
  preset: "twitch_gaming",
  maxClips: 15,
  useNvenc: false,
  cleanup: false,
  resume: false,
  exportAllClips: false,
};

export default function ReelsView({ apiReady, health, consumePendingVod, onOpenLibrary }: Props) {
  const [form, setForm] = useState<JobFormValues>(defaultForm);

  useEffect(() => {
    const path = consumePendingVod?.();
    if (path) setForm((f) => ({ ...f, videoPath: path }));
  }, [consumePendingVod]);
  const [highlights, setHighlights] = useState<HighlightItem[]>([]);
  const [sourceVideoUrl, setSourceVideoUrl] = useState("");
  const [previewWarning, setPreviewWarning] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [clips, setClips] = useState<ClipItem[]>([]);
  const [outputDir, setOutputDir] = useState("");
  const [cleared, setCleared] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [sourceWidth, setSourceWidth] = useState(0);
  const [sourceHeight, setSourceHeight] = useState(0);
  const [youtubePresets, setYoutubePresets] = useState<ResolutionPreset[]>([]);
  const [reelsPresets, setReelsPresets] = useState<ResolutionPreset[]>([]);
  const [youtubeResolution, setYoutubeResolution] = useState<ResolutionPreset | null>(null);
  const [reelsResolution, setReelsResolution] = useState<ResolutionPreset | null>(null);

  const loadHighlights = useCallback(async (jobId: string) => {
    try {
      const data = await fetchHighlights(jobId);
      setHighlights(data.highlights);
      setSourceVideoUrl(data.source_video_url);
      setSourceWidth(data.source_width ?? 0);
      setSourceHeight(data.source_height ?? 0);
      setYoutubePresets(data.youtube_presets ?? []);
      setReelsPresets(data.reels_presets ?? []);
      if (data.default_youtube) setYoutubeResolution(data.default_youtube);
      if (data.default_reels) setReelsResolution(data.default_reels);
      setSelected(new Set(data.highlights.map((h) => h.index)));
      // Do not auto-select row 0: that would mount <video> and seek immediately on huge VODs.
      setActiveIndex(null);
      const sizeGb = (data.preview_size_bytes ?? 0) / 1e9;
      if (data.preview_is_full_source && sizeGb >= 2) {
        setPreviewWarning(
          `O preview usa o VOD completo (${sizeGb.toFixed(1)} GB). Clique em um highlight para carregar o vídeo — pode demorar no primeiro seek.`
        );
      } else {
        setPreviewWarning(null);
      }
    } catch {
      /* not ready yet */
    }
  }, []);

  const loadClips = useCallback(async (jobId: string) => {
    try {
      const data = await fetchClips(jobId);
      setClips(data.clips);
      setOutputDir(data.output_dir);
    } catch {
      /* not ready yet */
    }
  }, []);

  const onCompleted = useCallback(
    (state: JobState) => {
      setExporting(false);
      setCleared(false);
      loadHighlights(state.id);
      if (state.clips_exported) loadClips(state.id);
    },
    [loadClips, loadHighlights]
  );

  const ctrl = useJobController({ onCompleted, onFailed: () => setExporting(false) });
  const { job, error, running, start, cancel, reset, setError } = ctrl;

  const resetUi = useCallback(() => {
    setHighlights([]);
    setSourceVideoUrl("");
    setPreviewWarning(null);
    setSelected(new Set());
    setActiveIndex(null);
    setClips([]);
    setOutputDir("");
    setCleared(true);
    setExporting(false);
    setSourceWidth(0);
    setSourceHeight(0);
    setYoutubePresets([]);
    setReelsPresets([]);
    setYoutubeResolution(null);
    setReelsResolution(null);
  }, []);

  const showReview = job?.status === "completed" && highlights.length > 0 && !cleared;
  const showGallery =
    job?.status === "completed" && clips.some((c) => c.youtube_url || c.reels_url) && !cleared;

  const startJob = async () => {
    const videoPath = form.videoPath.trim();
    if (!videoPath) return;
    if (!apiReady) {
      setError("API ainda não está pronta. Aguarde ou reinicie o servidor Python.");
      return;
    }
    resetUi();
    await start({
      video_path: videoPath,
      feature: "reels",
      preset: form.preset,
      mode: "gaming",
      max_clips: form.maxClips,
      use_nvenc: form.useNvenc,
      export_clips: form.exportAllClips,
    });
  };

  const runExport = async () => {
    if (!job || selected.size === 0) return;
    setError(null);
    setExporting(true);
    try {
      await exportHighlights(job.id, {
        highlight_indices: [...selected].sort((a, b) => a - b),
        use_nvenc: form.useNvenc,
        youtube_resolution: youtubeResolution
          ? { width: youtubeResolution.width, height: youtubeResolution.height }
          : undefined,
        reels_resolution: reelsResolution
          ? { width: reelsResolution.width, height: reelsResolution.height }
          : undefined,
      });
      ctrl.subscribe(job.id);
    } catch (e) {
      setExporting(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const onNewVideoUpload = useCallback(() => {
    reset();
    resetUi();
    setForm((f) => ({ ...f, resume: false }));
  }, [reset, resetUi]);

  return (
    <>
      {error && <p className="error">{error}</p>}

      <JobForm
        values={form}
        onChange={setForm}
        onSubmit={startJob}
        onNewVideo={onNewVideoUpload}
        onVideoChange={(videoPath) => setForm((f) => ({ ...f, videoPath }))}
        disabled={!!running || exporting || !apiReady}
        apiReady={apiReady}
        health={health}
      />

      <ProgressPanel job={job} onCancel={cancel} />

      {showReview && job && (
        <>
          <HighlightsReview
            jobId={job.id}
            highlights={highlights}
            sourceVideoUrl={sourceVideoUrl}
            previewWarning={previewWarning}
            selected={selected}
            onSelectedChange={setSelected}
            onPreview={setActiveIndex}
            activeIndex={activeIndex}
            disabled={running || exporting}
          />
          <div className="card" style={{ paddingTop: 0, marginTop: "-0.5rem", borderTop: "none" }}>
            {youtubeResolution && reelsResolution && (
              <ExportResolutionPicker
                sourceWidth={sourceWidth}
                sourceHeight={sourceHeight}
                youtubePresets={youtubePresets}
                reelsPresets={reelsPresets}
                youtubeResolution={youtubeResolution}
                reelsResolution={reelsResolution}
                onYoutubeChange={setYoutubeResolution}
                onReelsChange={setReelsResolution}
                disabled={!!running || exporting}
              />
            )}
            <button
              type="button"
              className="primary"
              disabled={selected.size === 0 || running || exporting}
              onClick={runExport}
            >
              {exporting
                ? "Exporting selected clips…"
                : `Generate ${selected.size} selected clip${selected.size === 1 ? "" : "s"}`}
            </button>
          </div>
        </>
      )}

      {showGallery && job && (
        <div>
          <ClipsGallery clips={clips} outputDir={outputDir || job.output_dir} />
          {onOpenLibrary && (
            <p style={{ marginTop: "0.75rem" }}>
              <button type="button" className="secondary" onClick={onOpenLibrary}>
                Ver na biblioteca de reels
              </button>
            </p>
          )}
        </div>
      )}

      {job && (job.status === "completed" || job.status === "failed") && (
        <CleanupPanel
          jobId={job.id}
          disabled={running || exporting}
          onCleared={() => {
            reset();
            resetUi();
            setForm((f) => ({ ...f, videoPath: "" }));
          }}
        />
      )}
    </>
  );
}
