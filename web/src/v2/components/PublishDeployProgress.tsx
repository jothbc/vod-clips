import type { PublishDeployStatus } from "../../api/v2";

const PHASE_LABELS: Record<string, string> = {
  auth: "Autenticação",
  upload: "Upload",
  thumbnail: "Capa",
  done: "Concluído",
  failed: "Erro",
};

interface Props {
  status: PublishDeployStatus;
}

export default function PublishDeployProgress({ status }: Props) {
  const phases = ["auth", "upload", "thumbnail", "done"];
  const phaseIndex = phases.indexOf(status.phase);

  return (
    <div className="v2-publish-upload">
      <div className="v2-publish-upload__header">
        <span className="v2-publish-upload__pulse" aria-hidden />
        <div>
          <strong className="v2-publish-upload__title">
            {status.status === "failed" ? "Falha no envio" : "Enviando para a plataforma"}
          </strong>
          <p className="v2-publish-upload__msg">{status.message}</p>
        </div>
        <span className="v2-publish-upload__pct">{Math.round(status.percent)}%</span>
      </div>

      <div className="v2-publish-upload__track" role="progressbar" aria-valuenow={status.percent} aria-valuemin={0} aria-valuemax={100}>
        <div
          className="v2-publish-upload__fill"
          style={{ width: `${Math.min(100, status.percent)}%` }}
        />
        <div className="v2-publish-upload__glow" style={{ left: `${Math.min(100, status.percent)}%` }} />
      </div>

      <div className="v2-publish-upload__phases">
        {phases.map((p, i) => {
          let cls = "v2-publish-upload__phase";
          if (status.status === "failed" && p === status.phase) cls += " v2-publish-upload__phase--failed";
          else if (p === status.phase && status.status === "running") cls += " v2-publish-upload__phase--active";
          else if (phaseIndex > i || status.status === "completed") cls += " v2-publish-upload__phase--done";
          return (
            <span key={p} className={cls}>
              {PHASE_LABELS[p] ?? p}
            </span>
          );
        })}
      </div>

      {status.error && <p className="v2-error">{status.error}</p>}
    </div>
  );
}
