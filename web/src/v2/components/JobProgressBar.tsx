import type { JobState } from "../../api/client";

const PHASES_BY_FEATURE: Record<string, string[]> = {
  v2_analyze: ["probe", "transcribe", "proxy", "heuristic", "done"],
  v2_export_clips: ["probe", "export", "done"],
  v2_captions: ["transcribe", "segments", "render", "done"],
  v2_cleanup: ["probe", "transcribe", "edl", "verify", "review", "render", "done"],
  v2_trim: ["probe", "render", "done"],
  cleanup: ["probe", "proxy", "transcribe", "edl", "verify", "render", "done"],
  captions: ["probe", "proxy", "transcribe", "segments", "render", "done"],
  reels: ["probe", "proxy", "transcribe", "scenes", "heuristic", "export", "done"],
};

interface Props {
  job: JobState | null;
  onCancel?: () => void;
}

export default function JobProgressBar({ job, onCancel }: Props) {
  if (!job || job.status === "queued") return null;

  const phases = PHASES_BY_FEATURE[job.feature ?? "reels"] ?? PHASES_BY_FEATURE.reels;
  const phaseIndex = phases.indexOf(job.phase);
  const logTail = (job.log || []).slice(-8).join("\n");
  const canCancel =
    !!onCancel && (job.status === "running" || job.status === "queued" || job.phase === "cancelling");

  return (
    <div className="v2-job-progress">
      <div className="v2-job-progress-header">
        <strong>
          {job.status === "running" && "Processando…"}
          {job.status === "awaiting_review" && "Revisão necessária"}
          {job.status === "completed" && "Concluído"}
          {job.status === "failed" && "Falhou"}
          {job.status === "cancelled" && "Cancelado"}
        </strong>
        <div className="v2-job-progress-actions">
          <span>{job.percent.toFixed(0)}%</span>
          {canCancel && (
            <button type="button" className="v2-btn v2-btn--ghost" onClick={onCancel}>
              Cancelar
            </button>
          )}
        </div>
      </div>
      <div className="v2-progress-bar">
        <div className="v2-progress-fill" style={{ width: `${Math.min(100, job.percent)}%` }} />
      </div>
      <p className="v2-card-meta">{job.message}</p>
      <div className="v2-phases">
        {phases
          .filter((p) => p !== "done")
          .map((p, i) => {
            let cls = "v2-phase";
            if (p === job.phase && job.status === "running") cls += " active";
            else if (phaseIndex > i || job.status === "completed" || job.status === "awaiting_review")
              cls += " done";
            return (
              <span key={p} className={cls}>
                {p}
              </span>
            );
          })}
      </div>
      {logTail && <pre className="v2-job-log">{logTail}</pre>}
      {job.error && <p className="v2-error">{job.error}</p>}
    </div>
  );
}
