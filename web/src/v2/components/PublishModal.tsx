import { useCallback, useEffect, useState } from "react";
import {
  createPublishSession,
  deployPublish,
  fetchPublishTargets,
  publishSessionThumbnailUrl,
  savePublishDraft,
  suggestPublishField,
  uploadSessionThumbnail,
  waitPublishDeploy,
  type PublishDeployStatus,
  type PublishSuggestField,
  type VideoDetail,
} from "../../api/v2";
import type { ClipFormat } from "./FormatToggle";
import PublishDeployProgress from "./PublishDeployProgress";
import PublishThumbnailDropzone from "./PublishThumbnailDropzone";
import PublishWalletPanel from "./PublishWalletPanel";

type Step = "compose" | "uploading" | "deploy";
type Platform = "youtube" | "short_form";
type ContentType = "game" | "other";
type YoutubeFormat = "video" | "shorts";

interface Props {
  video: VideoDetail;
  sourceFormat?: ClipFormat;
  onClose: () => void;
}

function AiButton({
  loading,
  disabled,
  onClick,
}: {
  loading: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`v2-publish-ai-btn${loading ? " v2-publish-ai-btn--loading" : ""}`}
      disabled={disabled || loading}
      onClick={onClick}
      aria-busy={loading}
    >
      <span className="v2-publish-ai-btn__spark" aria-hidden>
        ✦
      </span>
      {loading ? "Gerando…" : "Gerar com IA"}
    </button>
  );
}

export default function PublishModal({ video, sourceFormat, onClose }: Props) {
  const [step, setStep] = useState<Step>("compose");
  const [platform, setPlatform] = useState<Platform>("youtube");
  const [contentType, setContentType] = useState<ContentType>("game");
  const [gameName, setGameName] = useState("");
  const [videoContext, setVideoContext] = useState("");
  const [channelInfo, setChannelInfo] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [hasThumbnail, setHasThumbnail] = useState(false);
  const [thumbVersion, setThumbVersion] = useState(0);
  const [thumbUploading, setThumbUploading] = useState(false);
  const [generating, setGenerating] = useState<PublishSuggestField | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState("");
  const [targetPlatform, setTargetPlatform] = useState<string | null>(null);
  const [youtubeFormat, setYoutubeFormat] = useState<YoutubeFormat>("video");
  const [deploying, setDeploying] = useState(false);
  const [deployStatus, setDeployStatus] = useState<PublishDeployStatus | null>(null);
  const [deployResult, setDeployResult] = useState<{ watch_url?: string; platform_post_id: string } | null>(
    null
  );
  const [tab, setTab] = useState<"prep" | "wallet">("prep");

  useEffect(() => {
    let cancelled = false;
    setSessionLoading(true);
    void (async () => {
      try {
        const body = video.kind === "clip" && sourceFormat ? { source_format: sourceFormat } : {};
        const res = await createPublishSession(video.id, body);
        if (!cancelled) setSessionId(res.session_id);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Erro ao iniciar sessão");
      } finally {
        if (!cancelled) setSessionLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [video.id, video.kind, sourceFormat]);

  useEffect(() => {
    if (!targetId) {
      setTargetPlatform(null);
      return;
    }
    let cancelled = false;
    void fetchPublishTargets().then((res) => {
      if (cancelled) return;
      const t = res.targets.find((x) => x.id === targetId);
      setTargetPlatform(t?.platform ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [targetId]);

  const suggestContext = useCallback(
    () => ({
      platform,
      content_type: contentType,
      game_name: contentType === "game" ? gameName.trim() : "",
      video_context: videoContext.trim(),
      channel_info: channelInfo.trim(),
      title: title.trim(),
    }),
    [platform, contentType, gameName, videoContext, channelInfo, title]
  );

  async function runSuggest(field: PublishSuggestField) {
    if (!sessionId || !video.has_transcript) return;
    setGenerating(field);
    setError(null);
    try {
      const res = await suggestPublishField(sessionId, { field, ...suggestContext() });
      if (field === "title" && res.title) setTitle(res.title);
      if (field === "description" && res.description) setDescription(res.description);
      if (field === "tags" && res.tags) setTagsText(res.tags.join(", "));
      if (field === "thumbnail") {
        setHasThumbnail(true);
        setThumbVersion((v) => v + 1);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao gerar sugestão");
    } finally {
      setGenerating(null);
    }
  }

  async function handleThumbnailFile(file: File) {
    if (!sessionId) return;
    setThumbUploading(true);
    setError(null);
    try {
      await uploadSessionThumbnail(sessionId, file);
      setHasThumbnail(true);
      setThumbVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao enviar capa");
    } finally {
      setThumbUploading(false);
    }
  }

  async function handleDeploy() {
    if (!sessionId || !targetId) return;
    setDeploying(true);
    setError(null);
    setDeployStatus(null);
    const tags = tagsText
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    try {
      await savePublishDraft(sessionId, { title, description, tags, platform });
      const overrides: Record<string, unknown> = { title, description, tags };
      if (targetPlatform === "youtube") {
        overrides.youtube_format = youtubeFormat;
      }
      const started = await deployPublish({
        session_id: sessionId,
        target_id: targetId,
        item_index: 0,
        overrides,
      });
      setStep("uploading");
      setDeployStatus(started);
      const final = await waitPublishDeploy(started.deploy_id, setDeployStatus);
      if (final.status === "failed") {
        throw new Error(final.error || "Falha ao publicar");
      }
      setDeployResult({
        platform_post_id: final.platform_post_id ?? "",
        watch_url: final.watch_url,
      });
      setStep("deploy");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao publicar");
      setStep("compose");
    } finally {
      setDeploying(false);
    }
  }

  const thumbSrc =
    sessionId && hasThumbnail
      ? `${publishSessionThumbnailUrl(sessionId)}?v=${thumbVersion}`
      : "";
  const canSuggest = Boolean(sessionId && video.has_transcript && !sessionLoading);

  return (
    <div className="v2-modal-backdrop" onClick={onClose}>
      <div className="v2-modal v2-modal--wide v2-publish-modal" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <div>
            <h2>Publicar</h2>
            <p className="v2-publish-sub">Monte título, descrição, tags e capa — IA só quando você pedir</p>
          </div>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        <nav className="v2-publish-steps" aria-label="Etapas">
          {(["compose", "uploading", "deploy"] as Step[]).map((s, i) => (
            <span
              key={s}
              className={`v2-publish-step${step === s ? " v2-publish-step--active" : ""}${
                ["compose", "uploading", "deploy"].indexOf(step) > i ? " v2-publish-step--done" : ""
              }`}
            >
              {s === "compose" && "Preparar"}
              {s === "uploading" && "Enviando"}
              {s === "deploy" && "Enviado"}
            </span>
          ))}
        </nav>

        <div className="v2-publish-tabs">
          <button
            type="button"
            className={`v2-publish-tab${tab === "prep" ? " v2-publish-tab--active" : ""}`}
            onClick={() => setTab("prep")}
          >
            Preparação
          </button>
          <button
            type="button"
            className={`v2-publish-tab${tab === "wallet" ? " v2-publish-tab--active" : ""}`}
            onClick={() => setTab("wallet")}
          >
            Carteira
          </button>
        </div>

        <div className="v2-modal-body">
          {(error || sessionLoading) && (
            <p className={sessionLoading ? "v2-card-meta" : "v2-error"}>
              {sessionLoading ? "Preparando sessão…" : error}
            </p>
          )}

          {tab === "wallet" && (
            <PublishWalletPanel compact selectedTargetId={targetId} onSelectTarget={setTargetId} />
          )}

          {tab === "prep" && step === "compose" && (
            <div className="v2-publish-ticket">
              <p className="v2-card-meta">
                Preencha os campos manualmente ou use IA campo a campo. Nada é gerado automaticamente.
              </p>

              <div className="v2-form-grid">
                <label>
                  Plataforma
                  <select value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
                    <option value="youtube">YouTube</option>
                    <option value="short_form">Short-form (Reels/TikTok)</option>
                  </select>
                </label>
                <label>
                  Tipo de conteúdo
                  <select
                    value={contentType}
                    onChange={(e) => setContentType(e.target.value as ContentType)}
                  >
                    <option value="game">Jogo</option>
                    <option value="other">Outro</option>
                  </select>
                </label>
              </div>

              {contentType === "game" && (
                <label className="v2-publish-field">
                  Qual o jogo?
                  <input value={gameName} onChange={(e) => setGameName(e.target.value)} />
                </label>
              )}

              <label className="v2-publish-field">
                Contexto do vídeo
                <textarea rows={2} value={videoContext} onChange={(e) => setVideoContext(e.target.value)} />
              </label>

              <label className="v2-publish-field">
                Informações sobre o canal
                <textarea rows={2} value={channelInfo} onChange={(e) => setChannelInfo(e.target.value)} />
              </label>

              {!video.has_transcript && (
                <p className="v2-error">Obtenha a transcrição antes de usar sugestões de IA.</p>
              )}

              <div className="v2-publish-ticket__grid">
                <div className="v2-publish-thumb-frame">
                  <PublishThumbnailDropzone
                    sessionId={sessionId}
                    thumbSrc={thumbSrc}
                    uploading={thumbUploading}
                    onPick={handleThumbnailFile}
                  />
                  <AiButton
                    loading={generating === "thumbnail"}
                    disabled={!canSuggest}
                    onClick={() => void runSuggest("thumbnail")}
                  />
                </div>

                <div className="v2-publish-fields">
                  <div className="v2-publish-field-row">
                    <label className="v2-publish-field-row__label">
                      Título
                      <input
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        placeholder="Título do vídeo"
                      />
                    </label>
                    <AiButton
                      loading={generating === "title"}
                      disabled={!canSuggest}
                      onClick={() => void runSuggest("title")}
                    />
                  </div>

                  <div className="v2-publish-field-row v2-publish-field-row--stack">
                    <label className="v2-publish-field-row__label">
                      Descrição
                      <textarea
                        rows={5}
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        placeholder="Descrição para a plataforma"
                      />
                    </label>
                    <AiButton
                      loading={generating === "description"}
                      disabled={!canSuggest}
                      onClick={() => void runSuggest("description")}
                    />
                  </div>

                  <div className="v2-publish-field-row">
                    <label className="v2-publish-field-row__label">
                      Tags (vírgula)
                      <input
                        value={tagsText}
                        onChange={(e) => setTagsText(e.target.value)}
                        placeholder="tag1, tag2, tag3"
                      />
                    </label>
                    <AiButton
                      loading={generating === "tags"}
                      disabled={!canSuggest}
                      onClick={() => void runSuggest("tags")}
                    />
                  </div>
                </div>
              </div>

              {targetPlatform === "youtube" && (
                <div className="v2-publish-format">
                  <span className="v2-publish-format__label">Formato no YouTube</span>
                  <div className="v2-publish-format__toggle" role="group" aria-label="Formato no YouTube">
                    <button
                      type="button"
                      className={`v2-publish-format__opt${youtubeFormat === "video" ? " v2-publish-format__opt--active" : ""}`}
                      onClick={() => setYoutubeFormat("video")}
                    >
                      <span className="v2-publish-format__icon" aria-hidden>
                        ▭
                      </span>
                      Vídeo
                    </button>
                    <button
                      type="button"
                      className={`v2-publish-format__opt${youtubeFormat === "shorts" ? " v2-publish-format__opt--active" : ""}`}
                      onClick={() => setYoutubeFormat("shorts")}
                    >
                      <span className="v2-publish-format__icon v2-publish-format__icon--short" aria-hidden>
                        ▮
                      </span>
                      Shorts
                    </button>
                  </div>
                  <p className="v2-card-meta">
                    Shorts adiciona #Shorts na descrição e tag — ideal para vertical até 60s.
                  </p>
                </div>
              )}

              <div className="v2-modal-actions">
                <button type="button" className="v2-btn" onClick={() => setTab("wallet")}>
                  Escolher destino na carteira
                </button>
                <button
                  type="button"
                  className="v2-btn v2-btn--primary"
                  disabled={!targetId || !sessionId || deploying || !title.trim()}
                  onClick={() => void handleDeploy()}
                >
                  {deploying ? "Enviando…" : "Publicar no destino"}
                </button>
              </div>
              {targetId && (
                <p className="v2-card-meta">Destino selecionado — título obrigatório para publicar.</p>
              )}
            </div>
          )}

          {tab === "prep" && step === "uploading" && deployStatus && (
            <PublishDeployProgress status={deployStatus} />
          )}

          {tab === "prep" && step === "deploy" && deployResult && (
            <div className="v2-publish-done">
              <p className="v2-publish-done__msg">Publicado com sucesso.</p>
              {deployResult.watch_url && (
                <a
                  href={deployResult.watch_url}
                  target="_blank"
                  rel="noreferrer"
                  className="v2-btn v2-btn--primary"
                >
                  Abrir no YouTube
                </a>
              )}
              {!deployResult.watch_url && deployResult.platform_post_id && (
                <p className="v2-card-meta">ID: {deployResult.platform_post_id}</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
