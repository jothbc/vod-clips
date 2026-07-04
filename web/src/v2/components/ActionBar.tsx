import { useState } from "react";
import { postMetadata, type VideoDetail } from "../../api/v2";

interface Props {
  video: VideoDetail;
  onRefresh: () => void;
  onGenerateClips: () => void;
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
  onRefresh,
  onGenerateClips,
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
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const isOriginal = video.kind === "original";

  async function run(action: string, fn: () => Promise<unknown>, successMsg?: string) {
    setBusy(action);
    setMessage(null);
    try {
      await fn();
      setMessage(successMsg ?? `${action} concluído.`);
      onRefresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Erro");
    } finally {
      setBusy(null);
    }
  }

  const anyBusy = !!busy || transformBusy;

  return (
    <div>
      <div className="v2-actions">
        <button
          type="button"
          className="v2-btn v2-btn--primary"
          disabled={anyBusy}
          onClick={() =>
            run(
              "metadata",
              () => postMetadata(video.id),
              video.has_transcript ? "Transcrição regenerada." : "Metadados obtidos."
            )
          }
        >
          {busy === "metadata" ? "Processando…" : video.has_transcript ? "Regenerar transcrição" : "Obter metadados"}
        </button>
        <button
          type="button"
          className="v2-btn"
          disabled={anyBusy || !video.has_transcript || !isOriginal}
          onClick={onGenerateClips}
        >
          Gerar clips
        </button>
        <button
          type="button"
          className="v2-btn"
          disabled={anyBusy || !video.has_transcript}
          onClick={onOpenCleanup}
        >
          Remover silêncios
        </button>
        <button
          type="button"
          className="v2-btn"
          disabled={anyBusy || !video.has_transcript}
          onClick={onOpenCaptions}
        >
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
          <button
            type="button"
            className="v2-btn"
            disabled={anyBusy}
            onClick={onTransformReel}
          >
            {transformBusy ? "Transformando…" : "Transformar em reel"}
          </button>
        )}
        <button
          type="button"
          className="v2-btn"
          disabled={anyBusy || !video.has_transcript}
          onClick={onOpenPublish}
        >
          Publicar
        </button>
      </div>
      {message && <p className="v2-card-meta">{message}</p>}
    </div>
  );
}
