import type { JobState } from "../api/client";

const PHASES_BY_FEATURE: Record<string, string[]> = {
  reels: ["probe", "proxy", "transcribe", "scenes", "heuristic", "export", "done"],
  cleanup: ["probe", "proxy", "transcribe", "silence", "llm_review", "render", "done"],
  captions: ["probe", "proxy", "transcribe", "captions", "render", "done"],
  publish: ["probe", "proxy", "transcribe", "llm", "thumbnail", "done"],
};

const DEFAULT_PHASES = PHASES_BY_FEATURE.reels;

interface Props {
  job: JobState | null;
  onCancel?: () => void;
}

export default function ProgressPanel({ job, onCancel }: Props) {
  if (!job || job.status === "queued") return null;

  const phases = PHASES_BY_FEATURE[job.feature ?? "reels"] ?? DEFAULT_PHASES;
  const phaseIndex = phases.indexOf(job.phase);
  const logTail = (job.log || []).slice(-12).join("\n");
  const canCancel = !!onCancel && (job.status === "running" || job.status === "queued");

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong>
          {job.status === "running" && "Processing…"}
          {job.status === "completed" && "Complete"}
          {job.status === "failed" && "Failed"}
        </strong>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span>{job.percent.toFixed(0)}%</span>
          {canCancel && (
            <button type="button" className="danger-button" onClick={onCancel}>
              Parar
            </button>
          )}
        </div>
      </div>

      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${Math.min(100, job.percent)}%` }} />
      </div>

      <p style={{ margin: "0.25rem 0", fontSize: "0.9rem" }}>{job.message}</p>

      <div className="phases">
        {phases
          .filter((p) => p !== "done")
          .map((p, i) => {
            const gated = p === "export" || p === "render";
            let cls = "phase";
            if (p === job.phase && job.status === "running") cls += " active";
            else if (
              phaseIndex > i ||
              (job.status === "completed" && (!gated || job.clips_exported))
            )
              cls += " done";
            return (
              <span key={p} className={cls}>
                {p}
              </span>
            );
          })}
      </div>

      {job.error && (
        <p className="error">
          {job.error}
          <span className="file-path-hint" style={{ display: "block", marginTop: "0.35rem" }}>
            Logs: temp/logs/reels.log · job: temp/outputs/&lt;job_id&gt;/job_error.log
          </span>
        </p>
      )}
      {job.warnings?.map((w, i) => (
        <p key={i} className="warn">
          {w}
        </p>
      ))}

      {logTail && <pre className="log">{logTail}</pre>}

      {job.output_dir && (
        <p className="file-path-hint" style={{ marginTop: "0.5rem" }}>
          Log detalhado: {job.output_dir}/activity.log · erros: {job.output_dir}/job_error.log ·
          global: temp/logs/reels.log
        </p>
      )}
    </div>
  );
}
