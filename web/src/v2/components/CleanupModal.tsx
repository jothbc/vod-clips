import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchCleanupConfig,
  fetchCleanupEdl,
  postCleanup,
  postCleanupRender,
  type CleanupEdlSpan,
  type CleanupJobBody,
  type VideoDetail,
} from "../../api/v2";
import { apiUrl } from "../../api/base";
import type { JobState } from "../../api/client";
import type { ClipFormat } from "./FormatToggle";
import JobProgressBar from "./JobProgressBar";
import { useV2Job } from "../hooks/useV2Job";

type Step = "config" | "analyzing" | "review" | "rendering" | "preview";

interface Props {
  video: VideoDetail;
  sourceFormat?: ClipFormat;
  onClose: () => void;
  onDone: () => void;
}

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function CleanupModal({ video, sourceFormat, onClose, onDone }: Props) {
  const [step, setStep] = useState<Step>("config");
  const [minGap, setMinGap] = useState(0.35);
  const [pad, setPad] = useState(0.05);
  const [silenceDb, setSilenceDb] = useState(-30);
  const [useSilencedetect, setUseSilencedetect] = useState(true);
  const [removeFillers, setRemoveFillers] = useState(true);
  const [useLlm, setUseLlm] = useState(true);
  const [exportYoutube, setExportYoutube] = useState(
    video.kind === "clip" && sourceFormat ? sourceFormat === "youtube" : true
  );
  const [exportReels, setExportReels] = useState(
    video.kind === "clip" && sourceFormat ? sourceFormat === "reels" : true
  );
  const [useNvenc, setUseNvenc] = useState(false);
  const [jobId, setJobId] = useState("");
  const [spans, setSpans] = useState<CleanupEdlSpan[]>([]);
  const [cutSet, setCutSet] = useState<Set<number>>(new Set());
  const [previewUrl, setPreviewUrl] = useState("");
  const [clipId, setClipId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const onAwaitingReview = useCallback(async (job: JobState) => {
    setJobId(job.id);
    try {
      const edl = await fetchCleanupEdl(job.id);
      setSpans(edl.spans);
      setCutSet(new Set(edl.spans.filter((s) => s.kind === "cut").map((s) => s.index)));
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "EDL indisponível");
    }
  }, []);

  const onRenderCompleted = useCallback((job: JobState) => {
    if (job.result_clip_id) {
      setClipId(job.result_clip_id);
      fetch(apiUrl(`/api/v2/videos/${encodeURIComponent(job.result_clip_id)}`))
        .then((r) => r.json())
        .then((detail) => {
          const urls = detail.stream_urls as Record<string, string> | undefined;
          const fmt = exportYoutube ? "youtube" : "reels";
          const rel = urls?.[fmt] || detail.stream_url;
          if (rel) setPreviewUrl(apiUrl(rel));
        })
        .catch(() => {});
    }
    setStep("preview");
  }, [exportYoutube]);

  const analysisJob = useV2Job({
    onAwaitingReview,
    onFailed: () => {
      setError("Falha na análise de silêncios");
      setStep("config");
    },
  });

  const renderJob = useV2Job({
    onCompleted: onRenderCompleted,
    onFailed: () => {
      setError("Falha na renderização");
      setStep("review");
    },
  });

  useEffect(() => {
    fetchCleanupConfig()
      .then((cfg) => {
        const d = cfg.defaults;
        if (typeof d.min_gap_seconds === "number") setMinGap(d.min_gap_seconds);
        if (typeof d.pad_seconds === "number") setPad(d.pad_seconds);
        if (typeof d.silence_noise_db === "number") setSilenceDb(d.silence_noise_db);
        if (typeof d.use_silencedetect === "boolean") setUseSilencedetect(d.use_silencedetect);
        if (typeof d.remove_fillers === "boolean") setRemoveFillers(d.remove_fillers);
        if (typeof d.use_llm === "boolean") setUseLlm(d.use_llm);
      })
      .catch(() => {});
  }, []);

  const timeSaved = useMemo(
    () =>
      spans.filter((s) => cutSet.has(s.index)).reduce((acc, s) => acc + (s.end - s.start), 0),
    [spans, cutSet]
  );

  async function startAnalysis() {
    setError(null);
    setStep("analyzing");
    const body: CleanupJobBody = {
      min_gap_seconds: minGap,
      pad_seconds: pad,
      silence_noise_db: silenceDb,
      use_silencedetect: useSilencedetect,
      remove_fillers: removeFillers,
      use_llm: useLlm,
      export_youtube: exportYoutube,
      export_reels: exportReels,
      use_nvenc: useNvenc,
      ...(video.kind === "clip" && sourceFormat ? { source_format: sourceFormat } : {}),
    };
    try {
      const res = await postCleanup(video.id, body);
      setJobId(res.job_id);
      analysisJob.waitForJob(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao iniciar");
      setStep("config");
    }
  }

  async function startRender() {
    if (!jobId) return;
    setError(null);
    setStep("rendering");
    try {
      const res = await postCleanupRender(jobId, {
        cut_indices: [...cutSet],
        export_youtube: exportYoutube,
        export_reels: exportReels,
        use_nvenc: useNvenc,
      });
      renderJob.waitForJob(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao renderizar");
      setStep("review");
    }
  }

  function toggleCut(index: number) {
    setCutSet((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  const activeJob = step === "rendering" ? renderJob.job : analysisJob.job;
  const activeRunning = step === "rendering" ? renderJob.running : analysisJob.running;
  const activeCancel = step === "rendering" ? renderJob.cancel : analysisJob.cancel;

  return (
    <div className="v2-modal-backdrop" onClick={onClose}>
      <div className="v2-modal v2-modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <h2>Remover silêncios</h2>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <div className="v2-modal-body">
          {(error || analysisJob.error || renderJob.error) && (
            <p className="v2-error">{error || analysisJob.error || renderJob.error}</p>
          )}

          {step === "config" && (
            <>
              <p className="v2-card-meta">
                Detecta pausas e erros de fala, permite revisar cortes e exporta um novo clipe.
              </p>
              <div className="v2-form-grid">
                <label>
                  Gap mínimo (s)
                  <input
                    type="number"
                    step={0.05}
                    value={minGap}
                    onChange={(e) => setMinGap(Number(e.target.value))}
                  />
                </label>
                <label>
                  Padding (s)
                  <input type="number" step={0.01} value={pad} onChange={(e) => setPad(Number(e.target.value))} />
                </label>
                <label>
                  Ruído silêncio (dB)
                  <input
                    type="number"
                    value={silenceDb}
                    onChange={(e) => setSilenceDb(Number(e.target.value))}
                  />
                </label>
              </div>
              <div className="v2-check-row">
                <label>
                  <input
                    type="checkbox"
                    checked={useSilencedetect}
                    onChange={(e) => setUseSilencedetect(e.target.checked)}
                  />
                  Silencedetect
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={removeFillers}
                    onChange={(e) => setRemoveFillers(e.target.checked)}
                  />
                  Remover fillers
                </label>
                <label>
                  <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
                  Revisão LLM
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={exportYoutube}
                    onChange={(e) => setExportYoutube(e.target.checked)}
                  />
                  Exportar desktop
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={exportReels}
                    onChange={(e) => setExportReels(e.target.checked)}
                  />
                  Exportar mobile
                </label>
                <label>
                  <input type="checkbox" checked={useNvenc} onChange={(e) => setUseNvenc(e.target.checked)} />
                  NVENC (GPU)
                </label>
              </div>
              <div className="v2-modal-actions">
                <button type="button" className="v2-btn v2-btn--primary" onClick={startAnalysis}>
                  Analisar
                </button>
              </div>
            </>
          )}

          {(step === "analyzing" || step === "rendering") && (
            <>
              <JobProgressBar job={activeJob} onCancel={activeCancel} />
              {!activeRunning && activeJob?.status === "failed" && (
                <button type="button" className="v2-btn" onClick={() => setStep("config")}>
                  Voltar
                </button>
              )}
            </>
          )}

          {step === "review" && (
            <>
              <p className="v2-card-meta">
                Tempo economizado: ~{fmtTime(timeSaved)} — selecione os cortes a aplicar.
              </p>
              <div className="v2-edl-list">
                {spans
                  .filter((s) => s.kind === "cut")
                  .map((s) => (
                    <label key={s.index} className="v2-edl-item">
                      <input
                        type="checkbox"
                        checked={cutSet.has(s.index)}
                        onChange={() => toggleCut(s.index)}
                      />
                      <span className="v2-edl-time">
                        {fmtTime(s.start)} – {fmtTime(s.end)}
                      </span>
                      <span className="v2-edl-text">{s.text || s.reason || s.source}</span>
                    </label>
                  ))}
              </div>
              <div className="v2-modal-actions">
                <button type="button" className="v2-btn" onClick={() => setStep("config")}>
                  Voltar
                </button>
                <button type="button" className="v2-btn v2-btn--primary" onClick={startRender}>
                  Renderizar vídeo
                </button>
              </div>
            </>
          )}

          {step === "preview" && (
            <>
              <p className="v2-card-meta">Clipe salvo na galeria.</p>
              {previewUrl && (
                <div className="v2-player-wrap">
                  <video src={previewUrl} controls playsInline />
                </div>
              )}
              <div className="v2-modal-actions">
                {clipId && (
                  <Link to={`/watch/${clipId}`} className="v2-btn v2-btn--primary">
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
