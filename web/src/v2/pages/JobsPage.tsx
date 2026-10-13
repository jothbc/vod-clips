import { Link } from "react-router-dom";
import { cancelV2Job, type JobState } from "../../api/jobs";
import AppHeader from "../components/AppHeader";
import { useJobs } from "../context/JobContext";
import "../v2.css";

const STATUS_LABEL: Record<string, string> = {
  queued: "Na fila",
  running: "Processando",
  awaiting_review: "Aguardando revisão",
  completed: "Concluído",
  failed: "Falhou",
  cancelled: "Cancelado",
};

const FEATURE_LABEL: Record<string, string> = {
  v2_analyze: "Análise de destaques",
  v2_export_clips: "Geração de clips",
  v2_captions: "Legendas",
  v2_cleanup: "Remoção de silêncios",
  v2_trim: "Recorte",
};

function order(job: JobState): number {
  switch (job.status) {
    case "running":
      return 0;
    case "awaiting_review":
      return 1;
    case "queued":
      return 2;
    default:
      return 3;
  }
}

function watchTarget(job: JobState): string | null {
  const target = job.result_video_id || job.video_id;
  return target ? `/watch/${encodeURIComponent(target)}` : null;
}

export default function JobsPage() {
  const { jobs, refresh } = useJobs();
  const sorted = [...jobs].sort((a, b) => order(a) - order(b));

  async function handleCancel(id: string) {
    try {
      await cancelV2Job(id);
    } finally {
      refresh();
    }
  }

  return (
    <div className="v2-root">
      <div className="v2-shell">
        <AppHeader />
        <h1 className="v2-page-title">Jobs</h1>
        {sorted.length === 0 && <p className="v2-card-meta">Nenhum job registrado ainda.</p>}
        <div className="v2-jobs-list">
          {sorted.map((job) => {
            const target = job.status === "completed" ? watchTarget(job) : null;
            const active = job.status === "running" || job.status === "queued";
            return (
              <div key={job.id} className={`v2-job-row v2-job-row--${job.status}`}>
                <div className="v2-job-row-head">
                  <strong>{FEATURE_LABEL[job.feature ?? ""] ?? job.feature ?? "Job"}</strong>
                  <span className={`v2-job-badge v2-job-badge--${job.status}`}>
                    {STATUS_LABEL[job.status] ?? job.status}
                  </span>
                </div>
                {(job.status === "running" || job.status === "queued") && (
                  <div className="v2-progress-bar">
                    <div
                      className="v2-progress-fill"
                      style={{ width: `${Math.min(100, job.percent)}%` }}
                    />
                  </div>
                )}
                {job.message && <p className="v2-card-meta">{job.message}</p>}
                {job.error && <p className="v2-error">{job.error}</p>}
                <div className="v2-job-row-actions">
                  {target && (
                    <Link to={target} className="v2-btn v2-btn--ghost">
                      Ver vídeo
                    </Link>
                  )}
                  {active && (
                    <button
                      type="button"
                      className="v2-btn v2-btn--ghost"
                      onClick={() => handleCancel(job.id)}
                    >
                      Cancelar
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
