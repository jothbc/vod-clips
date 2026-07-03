import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchCaptionsConfig,
  postCaptions,
  type CaptionsJobBody,
  type VideoDetail,
} from "../../api/v2";
import { apiUrl } from "../../api/base";
import type { JobState } from "../../api/client";
import type { ClipFormat } from "./FormatToggle";
import JobProgressBar from "./JobProgressBar";
import { useV2Job } from "../hooks/useV2Job";

type Step = "config" | "processing" | "preview";

interface Props {
  video: VideoDetail;
  sourceFormat?: ClipFormat;
  onClose: () => void;
  onDone: () => void;
}

export default function CaptionsModal({ video, sourceFormat, onClose, onDone }: Props) {
  const [step, setStep] = useState<Step>("config");
  const [fonts, setFonts] = useState<{ id: string; label: string }[]>([]);
  const [fontId, setFontId] = useState("montserrat-bold");
  const [maxWords, setMaxWords] = useState(4);
  const [outputFormat, setOutputFormat] = useState<"reels" | "youtube" | "both">(
    video.kind === "clip" && sourceFormat ? sourceFormat : "reels"
  );
  const [useNvenc, setUseNvenc] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");
  const [clipId, setClipId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const onCompleted = useCallback((job: JobState) => {
    if (job.result_clip_id) {
      setClipId(job.result_clip_id);
      fetch(apiUrl(`/api/v2/videos/${encodeURIComponent(job.result_clip_id)}`))
        .then((r) => r.json())
        .then((detail) => {
          const urls = detail.stream_urls as Record<string, string> | undefined;
          const fmt =
            outputFormat === "youtube" ? "youtube" : outputFormat === "both" ? "reels" : "reels";
          const rel = urls?.[fmt] || detail.stream_url;
          if (rel) setPreviewUrl(apiUrl(rel));
        })
        .catch(() => {});
    }
    setStep("preview");
  }, [outputFormat]);

  const { job, error: jobError, running, waitForJob, cancel } = useV2Job({
    onCompleted,
    onFailed: () => setError("Falha ao gerar legendas"),
  });

  useEffect(() => {
    fetchCaptionsConfig()
      .then((cfg) => {
        setFonts(cfg.fonts);
        const d = cfg.defaults;
        if (typeof d.default_font === "string") setFontId(d.default_font);
        if (typeof d.max_words_per_line === "number") setMaxWords(d.max_words_per_line);
      })
      .catch(() => {});
  }, []);

  async function startCaptions() {
    setError(null);
    setStep("processing");
    const body: CaptionsJobBody = {
      font_id: fontId,
      max_words_per_line: maxWords,
      output_format: outputFormat,
      use_nvenc: useNvenc,
      ...(video.kind === "clip" && sourceFormat ? { source_format: sourceFormat } : {}),
    };
    try {
      const res = await postCaptions(video.id, body);
      waitForJob(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao iniciar");
      setStep("config");
    }
  }

  return (
    <div className="v2-modal-backdrop" onClick={onClose}>
      <div className="v2-modal v2-modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <h2>Gerar legendas</h2>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <div className="v2-modal-body">
          {(error || jobError) && <p className="v2-error">{error || jobError}</p>}

          {step === "config" && (
            <>
              <p className="v2-card-meta">Queima legendas estilo karaoke no vídeo e salva como clipe na galeria.</p>
              <div className="v2-form-grid">
                <label>
                  Fonte
                  <select value={fontId} onChange={(e) => setFontId(e.target.value)}>
                    {fonts.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Palavras por linha
                  <input
                    type="number"
                    min={1}
                    max={12}
                    value={maxWords}
                    onChange={(e) => setMaxWords(Number(e.target.value))}
                  />
                </label>
                <label>
                  Formato de saída
                  <select
                    value={outputFormat}
                    onChange={(e) => setOutputFormat(e.target.value as typeof outputFormat)}
                  >
                    <option value="reels">Mobile (9:16)</option>
                    <option value="youtube">Desktop (16:9)</option>
                    <option value="both">Ambos</option>
                  </select>
                </label>
              </div>
              <label className="v2-check-row">
                <input type="checkbox" checked={useNvenc} onChange={(e) => setUseNvenc(e.target.checked)} />
                NVENC (GPU) na renderização
              </label>
              <div className="v2-modal-actions">
                <button type="button" className="v2-btn v2-btn--primary" disabled={running} onClick={startCaptions}>
                  Gerar legendas
                </button>
              </div>
            </>
          )}

          {step === "processing" && (
            <>
              <JobProgressBar job={job} onCancel={cancel} />
              {!running && job?.status === "failed" && (
                <button type="button" className="v2-btn" onClick={() => setStep("config")}>
                  Voltar
                </button>
              )}
            </>
          )}

          {step === "preview" && (
            <>
              <p className="v2-card-meta">Clipe salvo na galeria.</p>
              {previewUrl && (
                <div className="v2-player-wrap v2-player-wrap--vertical" style={{ maxWidth: 360 }}>
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
