import type { JobState } from "../api/client";

const PHASES = ["probe", "proxy", "transcribe", "scenes", "heuristic", "vlm", "export", "done"];

interface Props {
  job: JobState | null;
}

export default function ProgressPanel({ job }: Props) {
  if (!job || job.status === "queued") return null;

  const phaseIndex = PHASES.indexOf(job.phase);
  const logTail = (job.log || []).slice(-12).join("\n");

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong>
          {job.status === "running" && "Processing…"}
          {job.status === "completed" && "Complete"}
          {job.status === "failed" && "Failed"}
        </strong>
        <span>{job.percent.toFixed(0)}%</span>
      </div>

      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${Math.min(100, job.percent)}%` }} />
      </div>

      <p style={{ margin: "0.25rem 0", fontSize: "0.9rem" }}>{job.message}</p>

      <div className="phases">
        {PHASES.filter((p) => p !== "done").map((p, i) => {
          let cls = "phase";
          if (p === job.phase && job.status === "running") cls += " active";
          else if (phaseIndex > i || job.status === "completed") cls += " done";
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
    </div>
  );
}
