import { useCallback, useMemo, useState } from "react";
import { apiUrl } from "../api/base";
import {
  fetchPublish,
  type JobState,
  type PublishContentType,
  type PublishItem,
  type PublishResponse,
} from "../api/client";
import CleanupPanel from "../components/CleanupPanel";
import MediaMultiSelectionField from "../components/MediaMultiSelectionField";
import ProgressPanel from "../components/ProgressPanel";
import { useMediaSelection } from "../context/MediaSelectionContext";
import { useMediaLibrary } from "../hooks/useMediaLibrary";
import { useJobController } from "../hooks/useJobController";

interface Props {
  apiReady: boolean;
  health: { ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null;
}

type Platform = "youtube" | "short_form";

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

export default function PublishView({ apiReady, health }: Props) {
  const { selectedMediaPaths } = useMediaSelection();
  const { storedVods, pickableClips } = useMediaLibrary(apiReady);
  const videoPaths = selectedMediaPaths;
  const [platform, setPlatform] = useState<Platform>("youtube");
  const [contentType, setContentType] = useState<PublishContentType>("game");
  const [gameName, setGameName] = useState("");
  const [videoContext, setVideoContext] = useState("");
  const [channelInfo, setChannelInfo] = useState("");
  const [publish, setPublish] = useState<PublishResponse | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const pathLabels = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const v of storedVods) labels[v.path] = v.filename;
    for (const c of pickableClips) labels[c.path] = c.title;
    return labels;
  }, [storedVods, pickableClips]);

  const pathSizes = useMemo(() => {
    const sizes: Record<string, number> = {};
    for (const v of storedVods) sizes[v.path] = v.size_bytes;
    for (const c of pickableClips) sizes[c.path] = c.size_bytes;
    return sizes;
  }, [storedVods, pickableClips]);

  const loadPublish = useCallback(async (jobId: string) => {
    try {
      const data = await fetchPublish(jobId);
      setPublish(data);
    } catch {
      /* not ready */
    }
  }, []);

  const { job, error, running, start, cancel, reset } = useJobController({
    onCompleted: (state: JobState) => {
      void loadPublish(state.id);
    },
  });

  const onGenerate = async () => {
    if (!videoPaths.length) return;
    setPublish(null);
    await start({
      feature: "publish",
      video_path: videoPaths[0],
      preset: "default",
      params: {
        video_paths: videoPaths,
        platform,
        content_type: contentType,
        game_name: contentType === "game" ? gameName.trim() : "",
        video_context: contentType === "other" ? videoContext.trim() : "",
        channel_info: channelInfo.trim(),
      },
    });
  };

  const markCopied = (key: string) => {
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1500);
  };

  const onCopy = async (key: string, text: string) => {
    try {
      await copyText(text);
      markCopied(key);
    } catch {
      /* ignore */
    }
  };

  const canGenerate = apiReady && videoPaths.length > 0 && !running;

  return (
    <>
      <MediaMultiSelectionField
        returnFeature="publish"
        labels={pathLabels}
        sizes={pathSizes}
        disabled={running}
      />

      <div className="card" style={{ marginTop: "1rem" }}>
        <label htmlFor="publish-platform">Plataforma</label>
        <select
          id="publish-platform"
          value={platform}
          onChange={(e) => setPlatform(e.target.value as Platform)}
          disabled={running}
        >
          <option value="youtube">YouTube (long-form)</option>
          <option value="short_form">Short-form (Shorts / Reels / TikTok)</option>
        </select>

        <fieldset style={{ marginTop: "1rem", border: "none", padding: 0 }}>
          <legend style={{ fontWeight: 600, marginBottom: "0.5rem" }}>Tipo de conteúdo</legend>
          <label style={{ display: "block", marginBottom: "0.35rem" }}>
            <input
              type="radio"
              name="publish-content-type"
              value="game"
              checked={contentType === "game"}
              onChange={() => setContentType("game")}
              disabled={running}
            />{" "}
            Vídeo de jogo
          </label>
          <label style={{ display: "block" }}>
            <input
              type="radio"
              name="publish-content-type"
              value="other"
              checked={contentType === "other"}
              onChange={() => setContentType("other")}
              disabled={running}
            />{" "}
            Outro assunto (paisagem, tutorial, vlog…)
          </label>
        </fieldset>

        {contentType === "game" ? (
          <div style={{ marginTop: "1rem" }}>
            <label htmlFor="publish-game">Qual o jogo?</label>
            <input
              id="publish-game"
              type="text"
              value={gameName}
              onChange={(e) => setGameName(e.target.value)}
              placeholder="Ex.: Elden Ring, Minecraft, Valorant"
              disabled={running}
              style={{ width: "100%", maxWidth: 480 }}
            />
            <p className="subtitle" style={{ marginTop: "0.35rem" }}>
              Opcional, mas melhora título e tags. Se vazio, a IA tenta inferir pelo áudio.
            </p>
          </div>
        ) : (
          <div style={{ marginTop: "1rem" }}>
            <label htmlFor="publish-video-context">Qual o contexto do vídeo?</label>
            <textarea
              id="publish-video-context"
              value={videoContext}
              onChange={(e) => setVideoContext(e.target.value)}
              placeholder="Ex.: timelapse de paisagem na Patagônia ao pôr do sol; vlog de viagem; tutorial de edição no Premiere"
              disabled={running}
              rows={3}
              style={{ width: "100%", maxWidth: 560 }}
            />
            <p className="subtitle" style={{ marginTop: "0.35rem" }}>
              Descreva o tema para títulos e descrições condizentes com o conteúdo.
            </p>
          </div>
        )}

        <div style={{ marginTop: "1rem" }}>
          <label htmlFor="publish-channel">Informações sobre o canal</label>
          <textarea
            id="publish-channel"
            value={channelInfo}
            onChange={(e) => setChannelInfo(e.target.value)}
            placeholder="Ex.: canal de gameplay casual em PT-BR, tom descontraído, público jovem, foco em momentos engraçados e dicas rápidas"
            disabled={running}
            rows={4}
            style={{ width: "100%", maxWidth: 560 }}
          />
          <p className="subtitle" style={{ marginTop: "0.35rem" }}>
            Tom de voz, nicho, público e estilo ajudam a IA a escrever como o seu canal.
          </p>
        </div>

        {!health?.ffmpeg && (
          <p className="warn" style={{ marginTop: "0.75rem" }}>
            ffmpeg não detectado — thumbnails não serão gerados.
          </p>
        )}
        {!health?.ollama && (
          <p className="warn" style={{ marginTop: "0.5rem" }}>
            Ollama offline — metadados usarão fallback do transcript.
          </p>
        )}

        <div style={{ marginTop: "1rem", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <button type="button" onClick={onGenerate} disabled={!canGenerate}>
            Gerar metadados
          </button>
          {job && (
            <button type="button" className="link-btn" onClick={reset} disabled={running}>
              Novo job
            </button>
          )}
        </div>
        {error && <p className="error">{error}</p>}
      </div>

      <ProgressPanel job={job} onCancel={running ? cancel : undefined} />

      {publish && publish.warnings.length > 0 && (
        <div className="card warn" style={{ marginTop: "1rem" }}>
          <strong>Avisos</strong>
          <ul>
            {publish.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {publish && publish.items.length > 0 && (
        <div style={{ marginTop: "1rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
          {publish.items.map((item: PublishItem) => (
            <PublishResultCard
              key={`${item.index}-${item.video_path}`}
              item={item}
              copiedKey={copiedKey}
              onCopy={onCopy}
            />
          ))}
        </div>
      )}

      {job?.status === "completed" && (
        <CleanupPanel jobId={job.id} disabled={running} onCleared={() => reset()} />
      )}
    </>
  );
}

function PublishResultCard({
  item,
  copiedKey,
  onCopy,
}: {
  item: PublishItem;
  copiedKey: string | null;
  onCopy: (key: string, text: string) => void;
}) {
  const thumbSrc = item.thumbnail_url ? apiUrl(item.thumbnail_url) : "";
  const tagsText = item.tags.join(", ");

  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>{item.source_label || item.video_path}</h3>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        {thumbSrc && (
          <a href={thumbSrc} download={`thumbnail-${item.index}.jpg`} title="Baixar thumbnail">
            <img
              src={thumbSrc}
              alt={`Thumbnail ${item.title}`}
              style={{ maxWidth: 280, borderRadius: 8, display: "block" }}
            />
          </a>
        )}
        <div style={{ flex: 1, minWidth: 240 }}>
          <p>
            <strong>Título</strong>
            <br />
            {item.title}
          </p>
          <p>
            <strong>Descrição</strong>
            <br />
            <span style={{ whiteSpace: "pre-wrap" }}>{item.description}</span>
          </p>
          {item.tags.length > 0 && (
            <p>
              <strong>Tags</strong>
              <br />
              {tagsText}
            </p>
          )}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            <button type="button" onClick={() => onCopy(`title-${item.index}`, item.title)}>
              {copiedKey === `title-${item.index}` ? "Copiado!" : "Copiar título"}
            </button>
            <button
              type="button"
              onClick={() => onCopy(`desc-${item.index}`, item.description)}
            >
              {copiedKey === `desc-${item.index}` ? "Copiado!" : "Copiar descrição"}
            </button>
            {tagsText && (
              <button type="button" onClick={() => onCopy(`tags-${item.index}`, tagsText)}>
                {copiedKey === `tags-${item.index}` ? "Copiado!" : "Copiar tags"}
              </button>
            )}
            {thumbSrc && (
              <a className="button" href={thumbSrc} download={`thumbnail-${item.index}.jpg`}>
                Baixar thumbnail
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
