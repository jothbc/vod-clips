import { useState } from "react";
import { postMetadata, postPublish, type VideoDetail } from "../../api/v2";

interface Props {
  video: VideoDetail;
  onRefresh: () => void;
  onGenerateClips: () => void;
  onOpenCaptions: () => void;
  onOpenCleanup: () => void;
  trimMode: boolean;
  onToggleTrim: () => void;
}

export default function ActionBar({
  video,
  onRefresh,
  onGenerateClips,
  onOpenCaptions,
  onOpenCleanup,
  trimMode,
  onToggleTrim,
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

  return (
    <div>
      <div className="v2-actions">
        <button
          type="button"
          className="v2-btn v2-btn--primary"
          disabled={!!busy}
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
          disabled={!!busy || !video.has_transcript || !isOriginal}
          onClick={onGenerateClips}
        >
          Gerar clips
        </button>
        <button
          type="button"
          className="v2-btn"
          disabled={!!busy || !video.has_transcript}
          onClick={onOpenCleanup}
        >
          Remover silêncios
        </button>
        <button
          type="button"
          className="v2-btn"
          disabled={!!busy || !video.has_transcript}
          onClick={onOpenCaptions}
        >
          Gerar legendas
        </button>
        <button
          type="button"
          className={`v2-btn${trimMode ? " v2-btn--primary" : ""}`}
          disabled={!!busy}
          onClick={onToggleTrim}
        >
          {trimMode ? "Fechar recorte" : "Recortar"}
        </button>
        <button
          type="button"
          className="v2-btn"
          disabled={!!busy || !video.has_transcript}
          onClick={() => run("publish", () => postPublish(video.id))}
        >
          {busy === "publish" ? "Processando…" : "Publicar"}
        </button>
      </div>
      {message && <p className="v2-card-meta">{message}</p>}
    </div>
  );
}
