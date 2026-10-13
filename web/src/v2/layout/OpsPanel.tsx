import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchRelated, type SystemStatus, type VideoSummary } from "../../api/v2";
import { cancelV2Job } from "../../api/jobs";
import { formatMmSs, formatRange } from "../../utils/timeFormat";
import { useBay } from "../context/BayContext";
import { useJobs } from "../context/JobContext";
import { useSystemStatus } from "../hooks/useSystemStatus";
import AudioOutputControl from "../components/AudioOutputControl";
import DockTooltip from "../components/DockTooltip";
import GaugeMeter from "../components/GaugeMeter";

function formatDuration(seconds: number): string {
  return formatMmSs(seconds);
}

function formatGb(mb: number): string {
  return (mb / 1024).toFixed(1);
}

function formatBadges(formats?: string[]): string {
  if (!formats?.length) return "";
  const labels = formats.map((f) => (f === "reels" ? "Mobile" : f === "youtube" ? "Desktop" : f));
  return labels.join(" · ");
}

function HealthDot({ status, tooltip }: { status: "ok" | "warn" | "error"; tooltip: string }) {
  return (
    <DockTooltip text={tooltip} className={`v2-health-dot v2-health-dot--${status}`} role="status" aria-label={tooltip}>
      <span className="v2-health-dot-core" aria-hidden />
    </DockTooltip>
  );
}

function HealthDots({ data }: { data: SystemStatus }) {
  const whisperOk =
    data.whisper.configured_device !== "cuda" || data.whisper.effective_device === "cuda";
  const cudaOk = data.cuda.libs_available;
  const cudaTooltip = data.cuda.nvenc_available
    ? "CUDA libs: disponíveis · NVENC habilitado"
    : cudaOk
      ? "CUDA libs: disponíveis"
      : "CUDA libs: indisponíveis";

  return (
    <div className="v2-health-dots">
      <HealthDot
        status={data.ffmpeg ? "ok" : "error"}
        tooltip={data.ffmpeg ? "ffmpeg/ffprobe: instalado" : "ffmpeg/ffprobe: não encontrado"}
      />
      <HealthDot
        status={data.yt_dlp ? "ok" : "error"}
        tooltip={data.yt_dlp ? "yt-dlp: instalado" : "yt-dlp: não encontrado"}
      />
      <HealthDot
        status={data.ollama.available ? "ok" : "warn"}
        tooltip={
          data.ollama.available
            ? `Ollama: disponível (${data.ollama.host})`
            : `Ollama: indisponível (${data.ollama.host})`
        }
      />
      <HealthDot
        status={whisperOk ? "ok" : "warn"}
        tooltip={`Whisper ${data.whisper.model} (${data.whisper.effective_device})`}
      />
      <HealthDot status={cudaOk ? "ok" : "warn"} tooltip={cudaTooltip} />
    </div>
  );
}

function featureLabel(feature?: string): string {
  switch (feature) {
    case "v2_analyze":
      return "Análise";
    case "v2_export_clips":
      return "Clips";
    case "v2_captions":
      return "Legendas";
    case "v2_cleanup":
      return "Silêncios";
    case "v2_trim":
      return "Recorte";
    default:
      return feature ?? "Job";
  }
}

export default function OpsPanel() {
  const { id } = useParams<{ id?: string }>();
  const { activeJobs, refresh } = useJobs();
  const { data, error, indicator } = useSystemStatus();
  const { openPublish, canPublish, opsOpen, closeDrawers } = useBay();
  const [related, setRelated] = useState<VideoSummary[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  useEffect(() => {
    if (!id) {
      setRelated([]);
      return;
    }
    let cancelled = false;
    (async () => {
      setRelatedLoading(true);
      try {
        const r = await fetchRelated(id);
        if (!cancelled) setRelated(r.items);
      } catch {
        if (!cancelled) setRelated([]);
      } finally {
        if (!cancelled) setRelatedLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  let gaugeIndex = 0;

  return (
    <aside className={`v2-bay-ops${opsOpen ? " v2-bay-ops--open" : ""}`} aria-label="Painel de ops">
      <div className="v2-bay-pane-h">
        <span>Ops</span>
        <small>dock</small>
      </div>

      <div className="v2-bay-ops-scroll">
        <div className="v2-bay-ops-block">
          <h3 className="v2-bay-ops-title">Jobs</h3>
          {activeJobs.length === 0 && <p className="v2-card-meta">Nenhum job ativo.</p>}
          {activeJobs.slice(0, 5).map((job) => (
            <div key={job.id} className="v2-bay-job">
              <div className="v2-bay-job-head">
                <span>{featureLabel(job.feature)}</span>
                <span className="v2-card-meta">{job.status}</span>
              </div>
              {job.message && <p className="v2-card-meta">{job.message}</p>}
              {(job.status === "running" || job.status === "queued") && (
                <div className="v2-progress-bar">
                  <div
                    className="v2-progress-fill"
                    style={{ width: `${Math.min(100, job.percent)}%` }}
                  />
                </div>
              )}
              {(job.status === "running" || job.status === "queued") && (
                <button
                  type="button"
                  className="v2-btn v2-btn--ghost"
                  style={{ marginTop: 6 }}
                  onClick={() => {
                    void cancelV2Job(job.id).finally(() => refresh());
                  }}
                >
                  Cancelar
                </button>
              )}
            </div>
          ))}
          <Link to="/jobs" className="v2-bay-ops-link" onClick={closeDrawers}>
            Ver todos →
          </Link>
        </div>

        <div className="v2-bay-ops-block">
          <h3 className="v2-bay-ops-title">Publish</h3>
          <button
            type="button"
            className="v2-btn v2-btn--primary"
            style={{ width: "100%" }}
            disabled={!canPublish || !openPublish}
            onClick={() => openPublish?.()}
          >
            Publicar seleção
          </button>
          {!id && (
            <p className="v2-card-meta" style={{ marginTop: 8 }}>
              Selecione uma mídia.
            </p>
          )}
        </div>

        <div className="v2-bay-ops-block">
          <h3 className="v2-bay-ops-title">Related</h3>
          {!id && <p className="v2-card-meta">Sem seleção.</p>}
          {id && relatedLoading && <p className="v2-loading">…</p>}
          {id && !relatedLoading && related.length === 0 && (
            <p className="v2-card-meta">Nenhum item relacionado.</p>
          )}
          {related.map((item) => (
            <Link
              key={item.id}
              to={`/watch/${encodeURIComponent(item.id)}`}
              className="v2-bay-related"
              onClick={closeDrawers}
            >
              <div
                className={`v2-bay-related-thumb${
                  item.format === "reels" ? " v2-bay-related-thumb--vertical" : ""
                }`}
              />
              <div>
                <p className="v2-card-title" style={{ margin: 0 }}>
                  {item.title}
                </p>
                <p className="v2-card-meta">
                  {item.start != null && item.end != null
                    ? formatRange(item.start, item.end)
                    : item.duration > 0
                      ? formatDuration(item.duration)
                      : ""}
                  {formatBadges(item.formats) ? ` · ${formatBadges(item.formats)}` : ""}
                </p>
              </div>
            </Link>
          ))}
        </div>

        <div className="v2-bay-ops-block">
          <h3 className="v2-bay-ops-title">
            System <span className={`v2-command-pill v2-command-pill--${indicator}`}>sys</span>
          </h3>
          {error && <p className="v2-error">{error}</p>}
          {!data && !error && <p className="v2-loading">Carregando…</p>}
          {data && (
            <>
              <div className="v2-bay-ops-gauges">
                {data.cpu && (
                  <GaugeMeter
                    label="CPU"
                    percent={data.cpu.percent}
                    tooltip={`Uso da CPU (${data.cpu.count} threads): ${data.cpu.percent.toFixed(0)}%`}
                    index={gaugeIndex++}
                  />
                )}
                {data.memory && (
                  <GaugeMeter
                    label="RAM"
                    percent={data.memory.percent}
                    tooltip={`Memória RAM: ${formatGb(data.memory.used_mb)} / ${formatGb(data.memory.total_mb)} GB (${data.memory.percent.toFixed(0)}%)`}
                    index={gaugeIndex++}
                  />
                )}
                {data.gpu?.utilization_percent != null && (
                  <GaugeMeter
                    label="GPU"
                    percent={data.gpu.utilization_percent}
                    tooltip={`Utilização da GPU (${data.gpu.name}): ${data.gpu.utilization_percent.toFixed(0)}%`}
                    index={gaugeIndex++}
                  />
                )}
                {data.gpu && data.gpu.memory_total_mb > 0 && (
                  <GaugeMeter
                    label="VRAM"
                    percent={(data.gpu.memory_used_mb / data.gpu.memory_total_mb) * 100}
                    tooltip={`VRAM: ${formatGb(data.gpu.memory_used_mb)} / ${formatGb(data.gpu.memory_total_mb)} GB (${((data.gpu.memory_used_mb / data.gpu.memory_total_mb) * 100).toFixed(0)}%)`}
                    index={gaugeIndex++}
                  />
                )}
                {data.active_job && (
                  <GaugeMeter
                    label="JOB"
                    percent={data.active_job.percent}
                    tooltip={`Job: ${data.active_job.feature} — ${data.active_job.phase} — ${data.active_job.message}`}
                    index={gaugeIndex++}
                  />
                )}
              </div>
              <HealthDots data={data} />
            </>
          )}
        </div>
      </div>

      <div className="v2-bay-ops-footer">
        <h3 className="v2-bay-ops-title">Áudio</h3>
        <AudioOutputControl />
      </div>
    </aside>
  );
}
