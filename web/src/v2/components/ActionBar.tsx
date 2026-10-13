import type { VideoDetail } from "../../api/v2";
import { useJobs } from "../context/JobContext";

interface Props {
  video: VideoDetail;
  onRefresh: () => void;
  onGenerateClip: () => void;
  onOpenCaptions: () => void;
  onOpenCleanup: () => void;
  onOpenPublish: () => void;
  onOpenWebcam?: () => void;
  canWebcam?: boolean;
  trimMode: boolean;
  onToggleTrim: () => void;
  canTransformReel?: boolean;
  transformBusy?: boolean;
  onTransformReel?: () => void;
}

export default function ActionBar({
  video,
  onGenerateClip,
  onOpenCaptions,
  onOpenCleanup,
  onOpenPublish,
  onOpenWebcam,
  canWebcam = false,
  trimMode,
  onToggleTrim,
  canTransformReel = false,
  transformBusy = false,
  onTransformReel,
}: Props) {
  const { hasActiveJob } = useJobs();
  const isOriginal = video.kind === "original";
  const videoBusy = hasActiveJob(video.id);
  const anyBusy = transformBusy || videoBusy;

  return (
    <div>
      <div className="v2-actions">
        <button
          type="button"
          className="v2-btn v2-btn--primary"
          disabled={anyBusy || !isOriginal}
          onClick={onGenerateClip}
        >
          Gerar clip
        </button>
        <button type="button" className="v2-btn" disabled={anyBusy} onClick={onOpenCleanup}>
          Remover silêncios
        </button>
        <button type="button" className="v2-btn" disabled={anyBusy} onClick={onOpenCaptions}>
          Gerar legendas
        </button>
        {canWebcam && onOpenWebcam && (
          <button type="button" className="v2-btn" disabled={anyBusy} onClick={onOpenWebcam}>
            Webcam
          </button>
        )}
        <button
          type="button"
          className={`v2-btn${trimMode ? " v2-btn--primary" : ""}`}
          disabled={anyBusy}
          onClick={onToggleTrim}
        >
          {trimMode ? "Fechar recorte" : "Recortar"}
        </button>
        {canTransformReel && onTransformReel && (
          <button type="button" className="v2-btn" disabled={anyBusy} onClick={onTransformReel}>
            {transformBusy ? "Transformando…" : "Transformar em reel"}
          </button>
        )}
        <button type="button" className="v2-btn" disabled={anyBusy} onClick={onOpenPublish}>
          Publicar
        </button>
      </div>
    </div>
  );
}
