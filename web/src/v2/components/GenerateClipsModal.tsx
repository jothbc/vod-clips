import { useCallback, useEffect, useState, type RefObject } from "react";
import {
  fetchHighlights,
  postAnalyzeHighlights,
  postGenerateClips,
  type HighlightItem,
  type ResolutionPreset,
  type VideoDetail,
} from "../../api/v2";
import ExportResolutionPicker from "./ExportResolutionPicker";
import { formatMmSs, formatRange, parseMmSs } from "../../utils/timeFormat";
import DockTooltip from "./DockTooltip";
import JobProgressBar from "./JobProgressBar";
import { useConfirmDialog } from "../hooks/useConfirmDialog";
import { useV2Job } from "../hooks/useV2Job";

type Step = "loading" | "idle" | "analyzing" | "review" | "exporting" | "done";

interface Props {
  video: VideoDetail;
  playerRef: RefObject<HTMLVideoElement>;
  onSeek: (t: number) => void;
  onClose: () => void;
  onDone: () => void;
}

interface HighlightRow extends HighlightItem {
  export_youtube: boolean;
  export_reels: boolean;
  include_webcam: boolean;
  burn_captions: boolean;
  cleanup_silence: boolean;
}

const WEBCAM_HINT =
  "Use a ação Webcam no vídeo desktop para marcar a região da câmera antes de incluir no mobile.";

function mapHighlights(items: HighlightItem[], hasWebcamRegion: boolean): HighlightRow[] {
  return items.map((h) => ({
    ...h,
    export_youtube: true,
    export_reels: true,
    include_webcam: hasWebcamRegion,
    burn_captions: false,
    cleanup_silence: false,
  }));
}

function TimeInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (seconds: number) => void;
}) {
  const [text, setText] = useState(formatMmSs(value));

  useEffect(() => {
    setText(formatMmSs(value));
  }, [value]);

  return (
    <label>
      {label}
      <input
        type="text"
        className="v2-time-input"
        value={text}
        placeholder="m:ss"
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          const parsed = parseMmSs(text);
          if (parsed !== null) {
            onChange(parsed);
            setText(formatMmSs(parsed));
          } else {
            setText(formatMmSs(value));
          }
        }}
      />
    </label>
  );
}

export default function GenerateClipsModal({ video, playerRef, onSeek, onClose, onDone }: Props) {
  const [step, setStep] = useState<Step>("loading");
  const [highlights, setHighlights] = useState<HighlightRow[]>([]);
  const [fromPersisted, setFromPersisted] = useState(false);
  const [exportedCount, setExportedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [maxClips, setMaxClips] = useState(15);
  const [prePad, setPrePad] = useState(2);
  const [postPad, setPostPad] = useState(2);
  const [sourceWidth, setSourceWidth] = useState(video.width || 0);
  const [sourceHeight, setSourceHeight] = useState(video.height || 0);
  const [youtubePresets, setYoutubePresets] = useState<ResolutionPreset[]>([]);
  const [reelsPresets, setReelsPresets] = useState<ResolutionPreset[]>([]);
  const [youtubeResolution, setYoutubeResolution] = useState<ResolutionPreset | null>(null);
  const [reelsResolution, setReelsResolution] = useState<ResolutionPreset | null>(null);
  const { confirm, dialog: confirmDialog } = useConfirmDialog();

  const hasWebcamRegion = Boolean(video.has_webcam_region);

  const applyHighlightsResponse = useCallback(
    (data: Awaited<ReturnType<typeof fetchHighlights>>, persisted: boolean) => {
      setHighlights(mapHighlights(data.highlights, hasWebcamRegion));
      setFromPersisted(persisted);
      if (data.source_width) setSourceWidth(data.source_width);
      if (data.source_height) setSourceHeight(data.source_height);
      if (data.youtube_presets) setYoutubePresets(data.youtube_presets);
      if (data.reels_presets) setReelsPresets(data.reels_presets);
      if (data.default_youtube) setYoutubeResolution(data.default_youtube);
      if (data.default_reels) setReelsResolution(data.default_reels);
    },
    [hasWebcamRegion]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchHighlights(video.id);
        if (cancelled) return;
        applyHighlightsResponse(data, true);
        setStep("review");
      } catch {
        if (cancelled) return;
        setStep("idle");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [video.id, applyHighlightsResponse]);

  const onAnalyzeDone = useCallback(async () => {
    try {
      const data = await fetchHighlights(video.id);
      applyHighlightsResponse(data, false);
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao carregar highlights");
      setStep("idle");
    }
  }, [applyHighlightsResponse, video.id]);

  const onExportDone = useCallback(async () => {
    const count = highlights.filter((h) => h.export_youtube || h.export_reels).length;
    setExportedCount(count);
    try {
      const data = await fetchHighlights(video.id);
      applyHighlightsResponse(data, true);
      setStep("review");
    } catch {
      setStep("done");
    }
  }, [applyHighlightsResponse, highlights, video.id]);

  const { job, running, waitForJob, cancel, error: jobError } = useV2Job({
    onCompleted: (state) => {
      if (state.feature === "v2_analyze") void onAnalyzeDone();
      else if (state.feature === "v2_export_clips") void onExportDone();
    },
    onFailed: () => {
      setStep((s) => (s === "analyzing" ? (fromPersisted || highlights.length ? "review" : "idle") : s === "exporting" ? "review" : s));
    },
  });

  async function startAnalyze() {
    setError(null);
    setStep("analyzing");
    try {
      const { job_id } = await postAnalyzeHighlights(video.id, { max_clips: maxClips });
      waitForJob(job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao iniciar análise");
      setStep(highlights.length ? "review" : "idle");
    }
  }

  async function startReanalyze() {
    const ok = await confirm({
      title: "Reanalisar highlights?",
      message: "Reanalisar apaga a lista atual de highlights e roda a análise de novo.",
      confirmLabel: "Reanalisar",
      danger: true,
    });
    if (!ok) return;
    await startAnalyze();
  }

  async function startExport() {
    const selected = highlights.filter((h) => h.export_youtube || h.export_reels);
    if (!selected.length) {
      setError("Selecione pelo menos um formato de exportação.");
      return;
    }
    setError(null);
    setStep("exporting");
    try {
      const { job_id } = await postGenerateClips(video.id, {
        selections: selected.map((h) => ({
          index: h.index,
          start: h.start,
          end: h.end,
          title: h.title,
          export_youtube: h.export_youtube,
          export_reels: h.export_reels,
          include_webcam: h.export_reels && h.include_webcam,
          burn_captions: h.burn_captions,
          cleanup_silence: h.cleanup_silence,
        })),
        pre_pad_seconds: prePad,
        post_pad_seconds: postPad,
      });
      waitForJob(job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao iniciar exportação");
      setStep("review");
    }
  }

  function updateRow(index: number, patch: Partial<HighlightRow>) {
    setHighlights((prev) => prev.map((h) => (h.index === index ? { ...h, ...patch } : h)));
  }

  async function handleClose() {
    if (running) {
      const ok = await confirm({
        title: "Fechar modal?",
        message: "Um job está em execução. O processamento continua em segundo plano.",
        confirmLabel: "Fechar mesmo assim",
      });
      if (!ok) return;
    }
    onClose();
  }

  const displayError = error || jobError;

  function renderMaxClipsField(id: string) {
    return (
      <label className="v2-field" htmlFor={id}>
        Quantidade de highlights
        <input
          id={id}
          type="number"
          min={1}
          max={50}
          value={maxClips}
          disabled={running}
          onChange={(e) => setMaxClips(Math.min(50, Math.max(1, parseInt(e.target.value, 10) || 15)))}
        />
      </label>
    );
  }

  return (
    <>
    <div className="v2-modal-backdrop" onClick={() => void handleClose()}>
      <div className="v2-modal v2-modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <h2>Gerar clips</h2>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={() => void handleClose()}>
            Fechar
          </button>
        </div>
        <div className="v2-modal-body">
          <div className="v2-player-wrap" style={{ marginBottom: 16 }}>
            <video
              ref={playerRef}
              src={video.stream_url}
              controls
              playsInline
              style={{ width: "100%", height: "100%" }}
            />
          </div>

          {displayError && <p className="v2-error">{displayError}</p>}

          {(step === "analyzing" || step === "exporting") && (
            <JobProgressBar job={job} onCancel={() => void cancel()} />
          )}

          {step === "loading" && <p className="v2-card-meta">Carregando highlights salvos…</p>}

          {step === "idle" && (
            <div className="v2-clips-analyze-panel">
              <p className="v2-card-meta">
                Analise o vídeo para detectar highlights. Nada roda automaticamente — clique para iniciar.
              </p>
              {renderMaxClipsField("v2-max-highlights")}
              <button type="button" className="v2-btn v2-btn--primary" onClick={() => void startAnalyze()}>
                Analisar highlights
              </button>
            </div>
          )}

          {step === "review" && (
            <>
              <div className="v2-clips-pending-banner">
                <div>
                  <strong>
                    {fromPersisted
                      ? "Previamente analisados e não gerados"
                      : "Highlights analisados"}
                  </strong>
                  <p className="v2-card-meta">
                    {highlights.length} item(ns). Fechar o modal não perde esta lista — ela fica salva
                    até você exportar ou reanalisar.
                  </p>
                </div>
              </div>

              <ul className="v2-highlights-list">
                {highlights.map((h) => (
                  <li key={h.index} className="v2-highlight-item">
                    <input
                      type="checkbox"
                      checked={h.export_youtube || h.export_reels}
                      onChange={(e) => {
                        if (!e.target.checked) {
                          updateRow(h.index, { export_youtube: false, export_reels: false });
                        } else {
                          updateRow(h.index, { export_youtube: true, export_reels: true });
                        }
                      }}
                    />
                    <div>
                      <strong>{h.title}</strong>
                      <p className="v2-card-meta">{h.reason}</p>
                      <p className="v2-highlight-range">{formatRange(h.start, h.end)}</p>
                      <div className="v2-highlight-trim">
                        <button type="button" className="v2-btn" onClick={() => onSeek(h.start)}>
                          ▶ Preview
                        </button>
                        <TimeInput
                          label="Início"
                          value={h.start}
                          onChange={(start) => updateRow(h.index, { start })}
                        />
                        <TimeInput
                          label="Fim"
                          value={h.end}
                          onChange={(end) => updateRow(h.index, { end })}
                        />
                      </div>
                      <div style={{ display: "flex", gap: 12, marginTop: 6, fontSize: "0.8rem" }}>
                        <label>
                          <input
                            type="checkbox"
                            checked={h.export_youtube}
                            onChange={(e) => updateRow(h.index, { export_youtube: e.target.checked })}
                          />{" "}
                          Desktop
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={h.export_reels}
                            onChange={(e) => {
                              const checked = e.target.checked;
                              updateRow(h.index, {
                                export_reels: checked,
                                include_webcam: checked ? h.include_webcam : false,
                              });
                            }}
                          />{" "}
                          Mobile
                        </label>
                        {h.export_reels && (
                          <DockTooltip
                            text={
                              hasWebcamRegion
                                ? "Incluir faixa da webcam no topo do mobile"
                                : WEBCAM_HINT
                            }
                          >
                            <label className={!hasWebcamRegion ? "v2-label--disabled" : ""}>
                              <input
                                type="checkbox"
                                checked={h.include_webcam}
                                disabled={!hasWebcamRegion}
                                onChange={(e) =>
                                  updateRow(h.index, { include_webcam: e.target.checked })
                                }
                              />{" "}
                              Incluir webcam
                            </label>
                          </DockTooltip>
                        )}
                      </div>
                    </div>
                    <span className="v2-card-meta">{h.score.toFixed(2)}</span>
                  </li>
                ))}
              </ul>

              <details className="v2-collapsible" open>
                <summary>Configurações de exportação</summary>
                <div className="v2-collapsible-content">
                  <label>
                    Pré-pad (s){" "}
                    <input
                      type="number"
                      step={0.5}
                      value={prePad}
                      onChange={(e) => setPrePad(parseFloat(e.target.value) || 0)}
                    />
                  </label>
                  <label style={{ marginLeft: 12 }}>
                    Pós-pad (s){" "}
                    <input
                      type="number"
                      step={0.5}
                      value={postPad}
                      onChange={(e) => setPostPad(parseFloat(e.target.value) || 0)}
                    />
                  </label>
                  <div style={{ marginTop: 12 }}>
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
                        disabled={running}
                      />
                    )}
                  </div>
                </div>
              </details>

              <div className="v2-modal-actions" style={{ marginTop: 16 }}>
                <button
                  type="button"
                  className="v2-btn v2-btn--primary"
                  disabled={running}
                  onClick={() => void startExport()}
                >
                  Exportar selecionados
                </button>
              </div>

              <div className="v2-clips-reanalyze">
                <p className="v2-card-meta">
                  Quer refazer a análise? Isso apaga a lista acima e gera uma nova.
                </p>
                {renderMaxClipsField("v2-max-highlights-reanalyze")}
                <button
                  type="button"
                  className="v2-btn"
                  disabled={running}
                  onClick={() => void startReanalyze()}
                >
                  Reanalisar highlights
                </button>
              </div>
            </>
          )}

          {step === "done" && (
            <div>
              <p className="v2-card-meta">
                Exportação concluída — {exportedCount} clip(s) processado(s). Não restam highlights
                pendentes.
              </p>
              <button type="button" className="v2-btn v2-btn--primary" onClick={onDone}>
                Fechar
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
    {confirmDialog}
    </>
  );
}
