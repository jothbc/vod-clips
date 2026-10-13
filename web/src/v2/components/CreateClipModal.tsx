import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { Link } from "react-router-dom";
import { apiUrl } from "../../api/base";
import { postCreateClip, type VideoDetail } from "../../api/v2";
import { formatMmSs } from "../../utils/timeFormat";
import type { JobState } from "../../api/jobs";
import JobProgressBar from "./JobProgressBar";
import { useV2Job } from "../hooks/useV2Job";

type Step = "edit" | "processing" | "done";
type DragMode = "move" | "in" | "out" | null;

interface Props {
  video: VideoDetail;
  playerRef: RefObject<HTMLVideoElement | null>;
  streamSrc?: string;
  onClose: () => void;
  onDone: () => void;
}

const MIN_CLIP_DUR = 5;
const MIN_ZOOM = 1;
const MAX_ZOOM = 24;

export default function CreateClipModal({
  video,
  playerRef,
  streamSrc,
  onClose,
  onDone,
}: Props) {
  const duration = video.duration > 0 ? video.duration : 0;
  const minDur = duration > 0 ? Math.min(MIN_CLIP_DUR, duration) : MIN_CLIP_DUR;
  const previewSrc = streamSrc || (video.stream_url ? apiUrl(video.stream_url) : "");
  const [step, setStep] = useState<Step>("edit");
  const [title, setTitle] = useState("");
  const [burnCaptions, setBurnCaptions] = useState(false);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(() => (video.duration > 0 ? video.duration : 0));
  const [zoom, setZoom] = useState(1);
  const [viewStart, setViewStart] = useState(0);
  const [clipId, setClipId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLVideoElement>(null);
  const rangeRef = useRef({ start: 0, end: video.duration > 0 ? video.duration : 0 });
  const dragRef = useRef<{
    mode: DragMode;
    originX: number;
    originStart: number;
    originEnd: number;
  } | null>(null);

  const viewDur = duration > 0 ? duration / zoom : 1;
  const clampedViewStart = Math.min(Math.max(0, viewStart), Math.max(0, duration - viewDur));
  const canSave = duration > 0 && title.trim().length > 0 && end - start >= minDur - 0.001;

  useEffect(() => {
    rangeRef.current = { start, end };
  }, [start, end]);

  // Full-range selection when duration becomes known / modal opens on a VOD.
  useEffect(() => {
    setStart(0);
    setEnd(duration);
    setViewStart(0);
    setZoom(1);
    rangeRef.current = { start: 0, end: duration };
  }, [duration, video.id]);

  const onCompleted = useCallback((job: JobState) => {
    setClipId(job.result_clip_id || job.result_video_id || "");
    setStep("done");
  }, []);

  const { job, error: jobError, running, waitForJob, cancel } = useV2Job({
    onCompleted,
    onFailed: () => setError("Falha ao criar clip"),
  });

  useEffect(() => {
    const mid = (start + end) / 2;
    const next = mid - viewDur / 2;
    setViewStart(Math.min(Math.max(0, next), Math.max(0, duration - viewDur)));
  }, [zoom, duration, viewDur]);

  function seekPreview(t: number, play = true) {
    const preview = previewRef.current;
    if (preview) {
      preview.currentTime = t;
      if (play) preview.play().catch(() => {});
    }
    const main = playerRef.current;
    if (main) {
      main.currentTime = t;
    }
  }

  function timeFromClientX(clientX: number): number {
    const el = trackRef.current;
    if (!el) return start;
    const rect = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return clampedViewStart + ratio * viewDur;
  }

  function onWheel(e: ReactWheelEvent) {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const nextZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * factor));
    const focus = timeFromClientX(e.clientX);
    const nextViewDur = duration / nextZoom;
    setZoom(nextZoom);
    setViewStart(
      Math.min(Math.max(0, focus - nextViewDur / 2), Math.max(0, duration - nextViewDur))
    );
  }

  function onPointerDown(mode: DragMode, e: ReactPointerEvent) {
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = { mode, originX: e.clientX, originStart: start, originEnd: end };
  }

  function onPointerMove(e: ReactPointerEvent) {
    const drag = dragRef.current;
    if (!drag || !drag.mode) return;
    const t = timeFromClientX(e.clientX);
    if (drag.mode === "in") {
      const ns = Math.min(Math.max(0, t), end - minDur);
      setStart(ns);
      seekPreview(ns, false);
    } else if (drag.mode === "out") {
      const ne = Math.max(Math.min(duration, t), start + minDur);
      setEnd(ne);
      seekPreview(Math.max(start, ne - 0.05), false);
    } else if (drag.mode === "move") {
      const el = trackRef.current;
      if (!el) return;
      const dx = e.clientX - drag.originX;
      const dt = (dx / el.getBoundingClientRect().width) * viewDur;
      const len = Math.max(drag.originEnd - drag.originStart, minDur);
      let ns = drag.originStart + dt;
      let ne = ns + len;
      if (ns < 0) {
        ns = 0;
        ne = len;
      }
      if (ne > duration) {
        ne = duration;
        ns = duration - len;
      }
      setStart(ns);
      setEnd(ne);
      seekPreview(ns, false);
    }
  }

  function onPointerUp() {
    const drag = dragRef.current;
    dragRef.current = null;
    const { start: s, end: e } = rangeRef.current;
    if (drag?.mode === "in" || drag?.mode === "move") {
      seekPreview(s, true);
    } else if (drag?.mode === "out") {
      seekPreview(Math.max(s, e - 0.5), true);
    }
  }

  async function handleSave() {
    if (!canSave) return;
    setError(null);
    setStep("processing");
    try {
      const res = await postCreateClip(video.id, {
        start,
        end,
        title: title.trim(),
        burn_captions: burnCaptions,
      });
      waitForJob(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao iniciar");
      setStep("edit");
    }
  }

  const leftPct = ((start - clampedViewStart) / viewDur) * 100;
  const widthPct = ((end - start) / viewDur) * 100;

  return (
    <div className="v2-modal-backdrop" onClick={onClose}>
      <div
        className="v2-modal v2-modal--wide v2-create-clip-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="v2-modal-header">
          <h2>Criar clipe</h2>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <div className="v2-modal-body v2-create-clip-body">
          {(error || jobError) && <p className="v2-error">{error || jobError}</p>}

          {step === "edit" && (
            <>
              <div className="v2-create-clip-preview">
                <p className="v2-create-clip-preview-label">Pré-visualização</p>
                <div className="v2-create-clip-preview-frame">
                  {previewSrc ? (
                    <video
                      ref={previewRef}
                      src={previewSrc}
                      controls
                      playsInline
                      onLoadedMetadata={() => seekPreview(start, false)}
                    />
                  ) : (
                    <p className="v2-card-meta">Vídeo indisponível</p>
                  )}
                </div>
              </div>

              <div className="v2-create-clip-times">
                <button type="button" className="v2-btn v2-btn--ghost" onClick={() => seekPreview(start)}>
                  Início {formatMmSs(start)}
                </button>
                <span className="v2-create-clip-duration">{formatMmSs(end - start)}</span>
                <button type="button" className="v2-btn v2-btn--ghost" onClick={() => seekPreview(end)}>
                  Fim {formatMmSs(end)}
                </button>
              </div>

              <div
                className="v2-create-clip-track"
                ref={trackRef}
                onWheel={onWheel}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
              >
                <div className="v2-create-clip-track-bg" />
                <div
                  className="v2-create-clip-selection"
                  style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                  onPointerDown={(e) => onPointerDown("move", e)}
                >
                  <button
                    type="button"
                    className="v2-create-clip-handle v2-create-clip-handle--in"
                    aria-label="Ajustar início"
                    onPointerDown={(e) => onPointerDown("in", e)}
                  />
                  <button
                    type="button"
                    className="v2-create-clip-handle v2-create-clip-handle--out"
                    aria-label="Ajustar fim"
                    onPointerDown={(e) => onPointerDown("out", e)}
                  />
                </div>
              </div>
              <p className="v2-card-meta v2-create-clip-zoom-hint">
                Role o mouse na timeline para zoom · {zoom.toFixed(1)}× ·{" "}
                {formatMmSs(clampedViewStart)}–{formatMmSs(clampedViewStart + viewDur)}
              </p>

              <label className="v2-create-clip-field">
                <span className="v2-create-clip-field-label">Título do clipe</span>
                <input
                  type="text"
                  value={title}
                  placeholder="Adicione um título (obrigatório)"
                  onChange={(e) => setTitle(e.target.value)}
                />
              </label>

              <label className="v2-check-row v2-create-clip-captions">
                <input
                  type="checkbox"
                  checked={burnCaptions}
                  onChange={(e) => setBurnCaptions(e.target.checked)}
                />
                <span>
                  <strong>Adicionar legendas</strong>
                  <span className="v2-card-meta">
                    Transcreve só o trecho selecionado e queima legendas no clipe.
                  </span>
                </span>
              </label>

              <div className="v2-modal-actions v2-create-clip-actions">
                <button type="button" className="v2-btn" onClick={onClose}>
                  Cancelar
                </button>
                <button
                  type="button"
                  className="v2-btn v2-btn--primary"
                  disabled={!canSave}
                  onClick={() => void handleSave()}
                >
                  Salvar clipe
                </button>
              </div>
            </>
          )}

          {step === "processing" && (
            <>
              <JobProgressBar job={job} onCancel={cancel} />
              {!running && job?.status === "failed" && (
                <button type="button" className="v2-btn" onClick={() => setStep("edit")}>
                  Voltar
                </button>
              )}
            </>
          )}

          {step === "done" && (
            <>
              <p className="v2-card-meta">Clip salvo na galeria.</p>
              <div className="v2-modal-actions">
                {clipId && (
                  <Link
                    to={`/watch/${clipId}`}
                    className="v2-btn v2-btn--primary"
                    onClick={() => onDone()}
                  >
                    Abrir clip
                  </Link>
                )}
                <button type="button" className="v2-btn" onClick={onDone}>
                  Concluir
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
