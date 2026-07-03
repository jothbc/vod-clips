import { useCallback, useEffect, useState, type RefObject } from "react";
import {
  fetchHighlights,
  postAnalyzeHighlights,
  postGenerateClips,
  type HighlightItem,
  type ResolutionPreset,
  type VideoDetail,
} from "../../api/v2";
import ExportResolutionPicker from "../../components/ExportResolutionPicker";
import { formatMmSs, formatRange, parseMmSs } from "../../utils/timeFormat";
import JobProgressBar from "./JobProgressBar";
import { useV2Job } from "../hooks/useV2Job";

type Step = "idle" | "analyzing" | "review" | "exporting" | "done";

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
  burn_captions: boolean;
  cleanup_silence: boolean;
}

function mapHighlights(items: HighlightItem[]): HighlightRow[] {
  return items.map((h) => ({
    ...h,
    export_youtube: true,
    export_reels: true,
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
  const [step, setStep] = useState<Step>("idle");
  const [highlights, setHighlights] = useState<HighlightRow[]>([]);
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

  const applyHighlightsResponse = useCallback((data: Awaited<ReturnType<typeof fetchHighlights>>) => {
    setHighlights(mapHighlights(data.highlights));
    if (data.source_width) setSourceWidth(data.source_width);
    if (data.source_height) setSourceHeight(data.source_height);
    if (data.youtube_presets) setYoutubePresets(data.youtube_presets);
    if (data.reels_presets) setReelsPresets(data.reels_presets);
    if (data.default_youtube) setYoutubeResolution(data.default_youtube);
    if (data.default_reels) setReelsResolution(data.default_reels);
  }, []);

  const onAnalyzeDone = useCallback(async () => {
    try {
      const data = await fetchHighlights(video.id);
      applyHighlightsResponse(data);
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao carregar highlights");
      setStep("idle");
    }
  }, [applyHighlightsResponse, video.id]);

  const onExportDone = useCallback(() => {
    const count = highlights.filter((h) => h.export_youtube || h.export_reels).length;
    setExportedCount(count);
    setStep("done");
  }, [highlights]);

  const { job, running, waitForJob, cancel, error: jobError } = useV2Job({
    onCompleted: (state) => {
      if (state.feature === "v2_analyze") void onAnalyzeDone();
      else if (state.feature === "v2_export_clips") onExportDone();
    },
    onFailed: () => {
      setStep((s) => (s === "analyzing" ? "idle" : s === "exporting" ? "review" : s));
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
      setStep("idle");
    }
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

  function handleClose() {
    if (running) {
      if (!window.confirm("Um job está em execução. Fechar o modal? O processamento continua em segundo plano.")) {
        return;
      }
    }
    onClose();
  }

  const displayError = error || jobError;

  return (
    <div className="v2-modal-backdrop" onClick={handleClose}>
      <div className="v2-modal v2-modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <h2>Gerar clips</h2>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={handleClose}>
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

          {step === "idle" && (
            <div>
              <p className="v2-card-meta">
                Analise o vídeo para detectar highlights. Nada roda automaticamente — clique para iniciar.
              </p>
              <label className="v2-field" htmlFor="v2-max-highlights">
                Quantidade de highlights
                <input
                  id="v2-max-highlights"
                  type="number"
                  min={1}
                  max={50}
                  value={maxClips}
                  onChange={(e) => setMaxClips(Math.min(50, Math.max(1, parseInt(e.target.value, 10) || 15)))}
                />
              </label>
              <button type="button" className="v2-btn v2-btn--primary" onClick={() => void startAnalyze()}>
                Analisar highlights
              </button>
            </div>
          )}

          {step === "review" && (
            <>
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
                            onChange={(e) => updateRow(h.index, { export_reels: e.target.checked })}
                          />{" "}
                          Mobile
                        </label>
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
              <button
                type="button"
                className="v2-btn v2-btn--primary"
                style={{ marginTop: 16 }}
                disabled={running}
                onClick={() => void startExport()}
              >
                Exportar selecionados
              </button>
            </>
          )}

          {step === "done" && (
            <div>
              <p className="v2-card-meta">Exportação concluída — {exportedCount} clip(s) processado(s).</p>
              <button type="button" className="v2-btn v2-btn--primary" onClick={onDone}>
                Fechar
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
