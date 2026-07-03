import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { Link } from "react-router-dom";
import { fetchSystemStatus, postTrim, postTrimFinalize, trimPreviewUrl, type TrimJobBody, type VideoDetail } from "../../api/v2";
import type { JobState } from "../../api/client";
import { formatMmSs, formatRange } from "../../utils/timeFormat";
import type { ClipFormat } from "./FormatToggle";
import JobProgressBar from "./JobProgressBar";
import { useV2Job } from "../hooks/useV2Job";
import {
  deleteSegment,
  duplicateSegment,
  gapsBetweenSegments,
  initialSegments,
  overlapCountAt,
  reorderSegments,
  splitAt,
  toKeepSpans,
  totalKeptDuration,
  type TrimSegment,
} from "../trim/trimSegments";

type Step = "edit" | "processing" | "preview";

interface Props {
  video: VideoDetail;
  duration: number;
  playerRef: RefObject<HTMLVideoElement | null>;
  sourceFormat?: ClipFormat;
  onClose: () => void;
  onDone: () => void;
}

const MAX_UNDO = 32;

export default function TrimEditor({
  video,
  duration,
  playerRef,
  sourceFormat,
  onClose,
  onDone,
}: Props) {
  const [step, setStep] = useState<Step>("edit");
  const [segments, setSegments] = useState<TrimSegment[]>(() => initialSegments(duration));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [undoStack, setUndoStack] = useState<TrimSegment[][]>([]);
  const [previewUrl, setPreviewUrl] = useState("");
  const [clipId, setClipId] = useState("");
  const [trimJobId, setTrimJobId] = useState("");
  const [saveMode, setSaveMode] = useState<"new_vod" | "replace" | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useNvenc, setUseNvenc] = useState(true);
  const [nvencAvailable, setNvencAvailable] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);
  const railRef = useRef<HTMLDivElement>(null);

  const safeDuration = Math.max(0.01, duration);

  useEffect(() => {
    fetchSystemStatus()
      .then((s) => {
        const ok = s.cuda.nvenc_available;
        setNvencAvailable(ok);
        setUseNvenc(ok);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    setSegments(initialSegments(duration));
    setSelectedId(null);
    setUndoStack([]);
  }, [video.id, duration]);

  useEffect(() => {
    const el = playerRef.current;
    if (!el) return;
    const onTime = () => setPlayhead(el.currentTime);
    el.addEventListener("timeupdate", onTime);
    return () => el.removeEventListener("timeupdate", onTime);
  }, [playerRef, video.id]);

  const pushUndo = useCallback((prev: TrimSegment[]) => {
    setUndoStack((stack) => [...stack.slice(-MAX_UNDO + 1), prev]);
  }, []);

  const applySegments = useCallback(
    (next: TrimSegment[], prev?: TrimSegment[]) => {
      if (prev) pushUndo(prev);
      setSegments(next);
    },
    [pushUndo]
  );

  const handleUndo = useCallback(() => {
    setUndoStack((stack) => {
      if (!stack.length) return stack;
      const prev = stack[stack.length - 1];
      setSegments(prev);
      return stack.slice(0, -1);
    });
  }, []);

  const handleSplit = useCallback(() => {
    const prev = segments;
    const next = splitAt(segments, playhead, safeDuration);
    if (next !== segments) applySegments(next, prev);
  }, [segments, playhead, safeDuration, applySegments]);

  const handleDelete = useCallback(() => {
    if (!selectedId || segments.length <= 1) return;
    const prev = segments;
    const next = deleteSegment(segments, selectedId);
    applySegments(next, prev);
    setSelectedId(null);
  }, [selectedId, segments, applySegments]);

  const handleDuplicate = useCallback(() => {
    if (!selectedId) return;
    const prev = segments;
    const next = duplicateSegment(segments, selectedId);
    if (next === segments) return;
    const newSeg = next[segments.findIndex((s) => s.id === selectedId) + 1];
    applySegments(next, prev);
    if (newSeg) setSelectedId(newSeg.id);
  }, [selectedId, segments, applySegments]);

  const handleDragStart = useCallback((id: string) => {
    setDragId(id);
  }, []);

  const handleDragEnd = useCallback(() => {
    setDragId(null);
    setDropTargetId(null);
  }, []);

  const handleDropOn = useCallback(
    (targetId: string) => {
      if (!dragId || dragId === targetId) return;
      const prev = segments;
      const next = reorderSegments(segments, dragId, targetId);
      applySegments(next, prev);
      setDragId(null);
      setDropTargetId(null);
    },
    [dragId, segments, applySegments]
  );

  const handleRailClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const rail = railRef.current;
      const videoEl = playerRef.current;
      if (!rail || !videoEl) return;
      const rect = rail.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const t = ratio * safeDuration;
      videoEl.currentTime = t;
      setPlayhead(t);
    },
    [playerRef, safeDuration]
  );

  const handleSelectSegment = useCallback(
    (seg: TrimSegment) => {
      setSelectedId(seg.id);
      const videoEl = playerRef.current;
      if (videoEl) {
        videoEl.currentTime = seg.start;
        setPlayhead(seg.start);
      }
    },
    [playerRef]
  );

  const onCompleted = useCallback((job: JobState) => {
    setTrimJobId(job.id);
    setPreviewUrl(trimPreviewUrl(job.id));
    setClipId("");
    setSaveMode(null);
    setStep("preview");
  }, []);

  const { job, error: jobError, running, waitForJob, cancel } = useV2Job({
    onCompleted,
    onFailed: () => setError("Falha ao gerar recorte"),
  });

  async function handleFinalize(mode: "new_vod" | "replace") {
    if (!trimJobId || finalizing) return;
    if (mode === "replace") {
      const label = video.kind === "clip" ? "clip atual" : "VOD atual";
      const ok = window.confirm(
        `Substituir o ${label}? O arquivo original será sobrescrito e não pode ser desfeito.`
      );
      if (!ok) return;
    }
    setError(null);
    setFinalizing(true);
    try {
      const res = await postTrimFinalize(trimJobId, mode);
      setSaveMode(mode);
      setClipId(res.video_id);
      if (mode === "replace") {
        onDone();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao salvar");
    } finally {
      setFinalizing(false);
    }
  }

  const replaceLabel = video.kind === "clip" ? "Substituir clip atual" : "Substituir VOD atual";

  async function handleRender() {
    setError(null);
    setStep("processing");
    const body: TrimJobBody = {
      keep_spans: toKeepSpans(segments),
      ...(nvencAvailable ? { use_nvenc: useNvenc } : { use_nvenc: false }),
      ...(video.kind === "clip" && sourceFormat ? { source_format: sourceFormat } : {}),
    };
    try {
      const res = await postTrim(video.id, body);
      waitForJob(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao iniciar");
      setStep("edit");
    }
  }

  const kept = totalKeptDuration(segments);
  const gaps = gapsBetweenSegments(segments, safeDuration);
  const playheadPct = (playhead / safeDuration) * 100;
  const canSplit = segments.some(
    (s) => playhead > s.start + 0.25 && playhead < s.end - 0.25
  );
  const selected = segments.find((s) => s.id === selectedId);

  return (
    <section className="v2-trim-panel" aria-label="Editor de recorte">
      <header className="v2-trim-header">
        <div>
          <h2 className="v2-trim-title">Recortar</h2>
          <p className="v2-trim-sub">
            Corte, duplique e reordene trechos. A sequência abaixo define a ordem do vídeo final.
          </p>
        </div>
        <div className="v2-trim-stats">
          <span className="v2-trim-stat">
            <em>Duração final</em>
            <strong>{formatMmSs(kept)}</strong>
          </span>
          <span className="v2-trim-stat">
            <em>Segmentos</em>
            <strong>{segments.length}</strong>
          </span>
        </div>
      </header>

      {(error || jobError) && <p className="v2-error">{error || jobError}</p>}

      {step === "edit" && (
        <>
          <div className="v2-trim-rail-wrap">
            <div
              ref={railRef}
              className="v2-trim-rail"
              role="slider"
              aria-label="Timeline"
              aria-valuemin={0}
              aria-valuemax={safeDuration}
              aria-valuenow={playhead}
              onClick={handleRailClick}
            >
              <div className="v2-trim-rail-inner">
                {gaps.map(([start, end]) => (
                  <div
                    key={`gap-${start}-${end}`}
                    className="v2-trim-gap"
                    style={{
                      left: `${(start / safeDuration) * 100}%`,
                      width: `${((end - start) / safeDuration) * 100}%`,
                    }}
                  />
                ))}
                {segments.map((seg, orderIdx) => {
                  const w = ((seg.end - seg.start) / safeDuration) * 100;
                  const left = (seg.start / safeDuration) * 100;
                  const isSelected = seg.id === selectedId;
                  const overlaps = overlapCountAt(segments, seg);
                  const stackIdx = segments
                    .slice(0, orderIdx + 1)
                    .filter((s) => s.start < seg.end - 0.01 && s.end > seg.start + 0.01).length - 1;
                  return (
                    <button
                      key={seg.id}
                      type="button"
                      className={`v2-trim-segment${isSelected ? " selected" : ""}${
                        overlaps > 1 ? " stacked" : ""
                      }`}
                      style={{
                        left: `${left}%`,
                        width: `${w}%`,
                        zIndex: 2 + orderIdx,
                        top: `${6 + stackIdx * 5}px`,
                        bottom: `${6 - stackIdx * 2}px`,
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSelectSegment(seg);
                      }}
                      title={`#${orderIdx + 1} · ${formatMmSs(seg.start)} – ${formatMmSs(seg.end)}`}
                    >
                      <span className="v2-trim-segment-order">{orderIdx + 1}</span>
                      <span className="v2-trim-segment-label">{formatMmSs(seg.end - seg.start)}</span>
                    </button>
                  );
                })}
                <div className="v2-trim-playhead" style={{ left: `${playheadPct}%` }}>
                  <span className="v2-trim-playhead-cap" />
                </div>
              </div>
            </div>
            <div className="v2-trim-time-row">
              <span>{formatMmSs(playhead)}</span>
              <span>{formatMmSs(safeDuration)}</span>
            </div>
          </div>

          <div className="v2-trim-sequence-wrap">
            <p className="v2-trim-sequence-label">Sequência de exportação</p>
            <div className="v2-trim-sequence" role="list" aria-label="Ordem dos trechos">
              {segments.map((seg, i) => {
                const isSelected = seg.id === selectedId;
                const isDragging = dragId === seg.id;
                const isDropTarget = dropTargetId === seg.id && dragId !== seg.id;
                return (
                  <div
                    key={seg.id}
                    role="listitem"
                    draggable
                    className={`v2-trim-seq-card${isSelected ? " selected" : ""}${
                      isDragging ? " dragging" : ""
                    }${isDropTarget ? " drop-target" : ""}`}
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = "move";
                      e.dataTransfer.setData("text/plain", seg.id);
                      handleDragStart(seg.id);
                    }}
                    onDragEnd={handleDragEnd}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.dataTransfer.dropEffect = "move";
                      setDropTargetId(seg.id);
                    }}
                    onDragLeave={() => {
                      setDropTargetId((id) => (id === seg.id ? null : id));
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      handleDropOn(seg.id);
                    }}
                    onClick={() => handleSelectSegment(seg)}
                  >
                    <span className="v2-trim-seq-grip" aria-hidden title="Arrastar">
                      ⠿
                    </span>
                    <span className="v2-trim-seq-idx">{i + 1}</span>
                    <span className="v2-trim-seq-times">{formatRange(seg.start, seg.end)}</span>
                    <span className="v2-trim-seq-dur">{formatMmSs(seg.end - seg.start)}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {selected && (
            <p className="v2-trim-selection">
              Selecionado #{segments.findIndex((s) => s.id === selectedId) + 1}:{" "}
              {formatRange(selected.start, selected.end)}
            </p>
          )}

          <div className="v2-trim-toolbar">
            <button
              type="button"
              className="v2-btn v2-trim-tool"
              disabled={!canSplit}
              onClick={handleSplit}
              title="Dividir no playhead"
            >
              <span className="v2-trim-icon" aria-hidden>
                ✂
              </span>
              Tesoura
            </button>
            <button
              type="button"
              className="v2-btn v2-trim-tool"
              disabled={!selectedId}
              onClick={handleDuplicate}
              title="Duplicar trecho na sequência"
            >
              <span className="v2-trim-icon" aria-hidden>
                ⧉
              </span>
              Duplicar
            </button>
            <button
              type="button"
              className="v2-btn v2-trim-tool"
              disabled={!selectedId || segments.length <= 1}
              onClick={handleDelete}
              title="Remover segmento"
            >
              <span className="v2-trim-icon" aria-hidden>
                ⌫
              </span>
              Remover
            </button>
            <button
              type="button"
              className="v2-btn v2-trim-tool"
              disabled={!undoStack.length}
              onClick={handleUndo}
            >
              Desfazer
            </button>
            {nvencAvailable && (
              <label className="v2-trim-nvenc">
                <input
                  type="checkbox"
                  checked={useNvenc}
                  onChange={(e) => setUseNvenc(e.target.checked)}
                />
                GPU (NVENC)
              </label>
            )}
            <div className="v2-trim-toolbar-spacer" />
            <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
              Cancelar
            </button>
            <button
              type="button"
              className="v2-btn v2-btn--primary"
              disabled={kept < 0.25 || running}
              onClick={() => void handleRender()}
            >
              Gerar recorte
            </button>
          </div>
        </>
      )}

      {step === "processing" && (
        <div className="v2-trim-processing">
          <JobProgressBar job={job} onCancel={cancel} />
        </div>
      )}

      {step === "preview" && (
        <div className="v2-trim-preview">
          {previewUrl && (
            <video src={previewUrl} controls className="v2-trim-preview-video" />
          )}
          <p className="v2-trim-preview-hint">
            {saveMode
              ? saveMode === "new_vod"
                ? "Novo VOD salvo na biblioteca."
                : "Vídeo original atualizado."
              : "Como deseja salvar este recorte?"}
          </p>
          <div className="v2-trim-preview-actions">
            {!saveMode && (
              <>
                <button
                  type="button"
                  className="v2-btn v2-btn--primary"
                  disabled={finalizing || !trimJobId}
                  onClick={() => void handleFinalize("new_vod")}
                >
                  Salvar como novo VOD
                </button>
                <button
                  type="button"
                  className="v2-btn v2-btn--danger"
                  disabled={finalizing || !trimJobId}
                  onClick={() => void handleFinalize("replace")}
                >
                  {replaceLabel}
                </button>
              </>
            )}
            {saveMode === "new_vod" && clipId && (
              <Link to={`/watch/${clipId}`} className="v2-btn v2-btn--primary">
                Abrir novo VOD
              </Link>
            )}
            <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
              Fechar
            </button>
            {(saveMode || finalizing) && (
              <button type="button" className="v2-btn" onClick={onDone} disabled={finalizing}>
                Concluir
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
