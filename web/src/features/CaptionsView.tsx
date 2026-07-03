import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl } from "../api/base";
import {
  fetchCaptionFonts,
  fetchCaptioned,
  fetchCaptions,
  renderCaptions,
  saveCaptions,
  type CaptionFont,
  type CaptionSegment,
  type CaptionsResponse,
  type JobState,
} from "../api/client";
import CleanupPanel from "../components/CleanupPanel";
import MediaSelectionField from "../components/MediaSelectionField";
import ProgressPanel from "../components/ProgressPanel";
import { useMediaSelection } from "../context/MediaSelectionContext";
import { useJobController } from "../hooks/useJobController";

interface Props {
  apiReady: boolean;
  health: { ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null;
}

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function CaptionsView({ apiReady, health }: Props) {
  const { selectedMedia, setSelectedMedia } = useMediaSelection();
  const videoPath = selectedMedia?.path ?? "";
  const [useNvenc, setUseNvenc] = useState(false);
  const [fonts, setFonts] = useState<CaptionFont[]>([]);
  const [fontId, setFontId] = useState("montserrat-bold");
  const [captions, setCaptions] = useState<CaptionsResponse | null>(null);
  const [segments, setSegments] = useState<CaptionSegment[]>([]);
  const [rendering, setRendering] = useState(false);
  const [captionedUrl, setCaptionedUrl] = useState("");
  const [captionedFilename, setCaptionedFilename] = useState("captioned.mp4");

  useEffect(() => {
    if (!apiReady) return;
    fetchCaptionFonts()
      .then((data) => {
        setFonts(data.fonts);
        if (data.fonts.length && !data.fonts.some((f) => f.id === fontId)) {
          setFontId(data.fonts[0].id);
        }
      })
      .catch(() => {
        /* fonts optional for display */
      });
  }, [apiReady, fontId]);

  const loadCaptions = useCallback(async (jobId: string) => {
    try {
      const data = await fetchCaptions(jobId);
      setCaptions(data);
      setSegments(data.segments);
      if (data.font_id) setFontId(data.font_id);
    } catch {
      /* not ready */
    }
  }, []);

  const loadCaptioned = useCallback(async (jobId: string) => {
    try {
      const data = await fetchCaptioned(jobId);
      setCaptionedUrl(apiUrl(data.url));
      setCaptionedFilename(data.filename);
    } catch {
      /* not ready */
    }
  }, []);

  const onCompleted = useCallback(
    (state: JobState) => {
      if (rendering || state.clips_exported) {
        setRendering(false);
        loadCaptioned(state.id);
        return;
      }
      loadCaptions(state.id);
    },
    [loadCaptions, loadCaptioned, rendering]
  );

  const ctrl = useJobController({ onCompleted, onFailed: () => setRendering(false) });
  const { job, error, running, start, subscribe, cancel, reset, setError } = ctrl;

  const captionedDuration = useMemo(
    () => segments.reduce((acc, s) => acc + Math.max(0, s.end - s.start), 0),
    [segments]
  );

  const resetUi = useCallback(() => {
    setCaptions(null);
    setSegments([]);
    setRendering(false);
    setCaptionedUrl("");
  }, []);

  const startJob = async () => {
    const path = videoPath.trim();
    if (!path) return;
    if (!apiReady) {
      setError("API ainda não está pronta.");
      return;
    }
    resetUi();
    await start({
      video_path: path,
      feature: "captions",
      preset: "default",
      params: { font_id: fontId },
    });
  };

  const restoreOriginal = () => {
    if (captions?.segments_original?.length) {
      setSegments(captions.segments_original.map((s) => ({ ...s, words: [...s.words] })));
    }
  };

  const updateSegmentText = (index: number, text: string) => {
    setSegments((prev) =>
      prev.map((s) => (s.index === index ? { ...s, text } : s))
    );
  };

  const runRender = async () => {
    if (!job || segments.length === 0) return;
    setError(null);
    setRendering(true);
    setCaptionedUrl("");
    try {
      await saveCaptions(job.id, { segments, font_id: fontId });
      await renderCaptions(job.id, {
        segments,
        font_id: fontId,
        use_nvenc: useNvenc,
        output_format: "reels",
      });
      subscribe(job.id);
    } catch (e) {
      setRendering(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const showReview =
    job?.status === "completed" && !!captions && segments.length > 0 && !captionedUrl && !rendering;

  return (
    <>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <MediaSelectionField
          returnFeature="captions"
          disabled={!!running || rendering || !apiReady}
          onClear={() => {
            reset();
            resetUi();
            setSelectedMedia(null);
          }}
        />

        {fonts.length > 0 && (
          <div style={{ marginTop: "0.75rem" }}>
            <label htmlFor="caption-font">Fonte das legendas</label>
            <select
              id="caption-font"
              value={fontId}
              disabled={!!running || rendering}
              onChange={(e) => setFontId(e.target.value)}
            >
              {fonts.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="check-row">
          <label>
            <input
              type="checkbox"
              checked={useNvenc}
              onChange={(e) => setUseNvenc(e.target.checked)}
              disabled={!!running || rendering}
            />
            NVENC (GPU) na renderização
          </label>
        </div>

        {health && (
          <p className="subtitle" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
            ffmpeg: {health.ffmpeg ? "ok" : "missing"}
          </p>
        )}

        <button
          type="button"
          className="primary"
          onClick={startJob}
          disabled={!!running || rendering || !apiReady || !videoPath.trim()}
        >
          Analisar vídeo
        </button>
      </div>

      <ProgressPanel job={job} onCancel={cancel} />

      {showReview && captions && (
        <div className="card">
          <h2 style={{ margin: "0 0 0.25rem", fontSize: "1.1rem" }}>Texto das legendas</h2>
          <p className="subtitle" style={{ marginBottom: "0.75rem" }}>
            Corrija o texto antes de gerar — as alterações aparecem no vídeo final.
            {segments.length} bloco{segments.length === 1 ? "" : "s"} · ~
            {fmtTime(captionedDuration)} legendado.
          </p>

          {captions.segments_original.length > 0 && (
            <button
              type="button"
              className="secondary"
              style={{ marginBottom: "0.75rem" }}
              onClick={restoreOriginal}
              disabled={rendering || running}
            >
              Restaurar transcrição original
            </button>
          )}

          <ul className="captions-editor-list">
            {segments.map((seg) => (
              <li key={seg.index} className="captions-editor-row">
                <span className="captions-editor-time">
                  {fmtTime(seg.start)} – {fmtTime(seg.end)}
                </span>
                <textarea
                  rows={2}
                  value={seg.text}
                  disabled={rendering || running}
                  onChange={(e) => updateSegmentText(seg.index, e.target.value)}
                />
              </li>
            ))}
          </ul>

          <button
            type="button"
            className="primary"
            onClick={runRender}
            disabled={rendering || running || segments.length === 0}
          >
            {rendering ? "Gerando vídeo…" : "Gerar vídeo"}
          </button>
        </div>
      )}

      {captionedUrl && (
        <div className="card">
          <h2 style={{ margin: "0 0 0.75rem", fontSize: "1.1rem" }}>Vídeo com legendas</h2>
          <div className="clip-card reels">
            <video controls preload="metadata" playsInline src={captionedUrl} />
            <div className="clip-meta">
              <a className="clip-download" href={captionedUrl} download={captionedFilename}>
                Baixar {captionedFilename}
              </a>
            </div>
          </div>
        </div>
      )}

      {job && (job.status === "completed" || job.status === "failed") && (
        <CleanupPanel
          jobId={job.id}
          disabled={running || rendering}
          onCleared={() => {
            reset();
            resetUi();
            setSelectedMedia(null);
          }}
        />
      )}
    </>
  );
}
