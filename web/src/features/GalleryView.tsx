import { useCallback, useEffect, useRef, useState } from "react";
import { getApiDisplayLabel } from "../api/base";
import {
  deleteReelJob,
  deleteStoredVod,
  formatBytes,
  uploadVodWithProgress,
  type PickableReelClip,
  type StoredVod,
} from "../api/client";
import ClipsGallery from "../components/ClipsGallery";
import { useMediaSelection } from "../context/MediaSelectionContext";
import { useMediaLibrary } from "../hooks/useMediaLibrary";
import { useTwitchDownloadQueue } from "../hooks/useTwitchDownloadQueue";
import { FEATURE_LABELS, type SelectedMedia } from "../types/mediaSelection";

interface Props {
  apiReady: boolean;
  health: { ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null;
}

function formatDate(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function statusLabel(status: string): string {
  switch (status) {
    case "queued":
      return "Na fila";
    case "downloading":
    case "running":
      return "Baixando";
    case "completed":
      return "Pronto";
    case "failed":
      return "Falhou";
    case "cancelled":
      return "Cancelado";
    default:
      return status;
  }
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

export default function GalleryView({ apiReady, health }: Props) {
  const {
    galleryPick,
    cancelGalleryPick,
    completeGalleryPick,
    setSelectedMedia,
    setSelectedMediaPaths,
  } = useMediaSelection();

  const {
    storedVods,
    libraryJobs,
    pickableClips,
    loading,
    error: libraryError,
    refresh,
    setLibraryJobs,
  } = useMediaLibrary(apiReady);

  const { downloads, error: twitchError, submitting, enqueueUrls, cancel, refresh: refreshTwitch } =
    useTwitchDownloadQueue(apiReady);

  const [urlText, setUrlText] = useState("");
  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  const [deletingJob, setDeletingJob] = useState<string | null>(null);
  const [multiPickPaths, setMultiPickPaths] = useState<string[]>([]);

  const uploadAbortRef = useRef<(() => void) | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadLoaded, setUploadLoaded] = useState(0);
  const [uploadTotal, setUploadTotal] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const pickMode = galleryPick !== null;
  const pickFilter = galleryPick?.filter ?? "any";
  const isMultiPick = galleryPick?.mode === "multi";

  useEffect(() => {
    if (galleryPick?.mode === "multi") {
      setMultiPickPaths(galleryPick.initialPaths ?? []);
    } else {
      setMultiPickPaths([]);
    }
  }, [galleryPick]);

  const prevCompletedRef = useRef(0);
  useEffect(() => {
    const n = downloads.filter((d) => d.status === "completed").length;
    if (n > prevCompletedRef.current) {
      void refresh();
    }
    prevCompletedRef.current = n;
  }, [downloads, refresh]);

  const canPickVod = pickFilter === "any" || pickFilter === "vod";
  const canPickClip = pickFilter === "any" || pickFilter === "clip";

  const pickSingle = useCallback(
    (media: SelectedMedia) => {
      setSelectedMedia(media);
      completeGalleryPick();
    },
    [setSelectedMedia, completeGalleryPick]
  );

  const pickVod = (vod: StoredVod) => {
    if (!pickMode || !canPickVod) return;
    if (isMultiPick) {
      setMultiPickPaths((prev) =>
        prev.includes(vod.path) ? prev.filter((p) => p !== vod.path) : [...prev, vod.path]
      );
      return;
    }
    pickSingle({ path: vod.path, kind: "vod", label: vod.filename });
  };

  const pickClip = (clip: PickableReelClip) => {
    if (!pickMode || !canPickClip) return;
    const fmt = clip.format === "reels" ? "Reels" : "YouTube";
    const label = `${clip.title} (${fmt})`;
    if (isMultiPick) {
      setMultiPickPaths((prev) =>
        prev.includes(clip.path) ? prev.filter((p) => p !== clip.path) : [...prev, clip.path]
      );
      return;
    }
    pickSingle({ path: clip.path, kind: "clip", label });
  };

  const confirmMultiPick = () => {
    setSelectedMediaPaths(multiPickPaths);
    completeGalleryPick();
  };

  const onEnqueue = async () => {
    const urls = urlText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (!urls.length) return;
    await enqueueUrls(urls);
    setUrlText("");
    void refresh();
  };

  const onFileInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadError(null);
    setUploading(true);
    setUploadProgress(0);
    setUploadLoaded(0);
    setUploadTotal(file.size);

    try {
      const handle = uploadVodWithProgress(file, (loaded, total) => {
        setUploadLoaded(loaded);
        setUploadTotal(total);
        const denom = total ?? file.size;
        if (denom > 0) setUploadProgress((loaded / denom) * 100);
      });
      uploadAbortRef.current = handle.abort;
      await handle.promise;
      void refresh();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      uploadAbortRef.current = null;
      setUploading(false);
      setUploadProgress(0);
      setUploadLoaded(0);
      setUploadTotal(null);
      e.target.value = "";
    }
  };

  const cancelUpload = () => {
    uploadAbortRef.current?.();
    uploadAbortRef.current = null;
  };

  const removeVod = async (vod: StoredVod) => {
    if (!confirm(`Remover ${vod.filename} (${formatSize(vod.size_bytes)})?`)) return;
    try {
      await deleteStoredVod(vod.path);
      void refresh();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDeleteJob = async (jobId: string, sourceVideo: string) => {
    const label = sourceVideo || jobId;
    if (!window.confirm(`Apagar todos os clipes desta sessão (${label})?`)) return;
    setDeletingJob(jobId);
    try {
      await deleteReelJob(jobId);
      setLibraryJobs((prev) => prev.filter((j) => j.job_id !== jobId));
      if (expandedJob === jobId) setExpandedJob(null);
      void refresh();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeletingJob(null);
    }
  };

  const active = downloads.filter(
    (d) => d.status === "queued" || d.status === "downloading" || d.status === "running"
  );
  const done = downloads.filter((d) => d.status === "completed");
  const failed = downloads.filter((d) => d.status === "failed" || d.status === "cancelled");
  const ingestDisabled = !apiReady || uploading || pickMode;

  const uploadLabel =
    uploadTotal && uploadTotal > 0
      ? `Enviando ${uploadProgress.toFixed(0)}% (${formatBytes(uploadLoaded)} / ${formatBytes(uploadTotal)})`
      : "Enviando…";

  return (
    <>
      {(libraryError || twitchError || uploadError) && (
        <p className="error">{libraryError || twitchError || uploadError}</p>
      )}

      {pickMode && galleryPick && (
        <div className="gallery-pick-bar card">
          <div>
            <strong>
              Selecionando{" "}
              {isMultiPick ? "vídeos" : "vídeo"} para{" "}
              {FEATURE_LABELS[galleryPick.returnFeature] ?? galleryPick.returnFeature}
            </strong>
            {isMultiPick && (
              <p className="subtitle" style={{ margin: "0.25rem 0 0" }}>
                Marque os itens desejados e confirme.
              </p>
            )}
          </div>
          <div className="gallery-pick-actions">
            {isMultiPick && (
              <button
                type="button"
                className="primary"
                disabled={multiPickPaths.length === 0}
                onClick={confirmMultiPick}
              >
                Confirmar ({multiPickPaths.length})
              </button>
            )}
            <button type="button" className="link-btn" onClick={cancelGalleryPick}>
              Cancelar
            </button>
          </div>
        </div>
      )}

      {!pickMode && (
        <div className="card gallery-ingest">
          <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.1rem" }}>Adicionar vídeos</h2>
          <p className="subtitle" style={{ marginBottom: "1rem" }}>
            Envie um MP4 local ou baixe VODs da Twitch. Arquivos ficam em{" "}
            <code>temp/vods/</code>.
          </p>

          {!apiReady && (
            <p className="warn" style={{ marginBottom: "0.75rem" }}>
              Aguardando API Python em <code>{getApiDisplayLabel()}</code>…
            </p>
          )}

          <div className="file-picker-row">
            <label className={`file-input-button ${ingestDisabled ? "disabled" : ""}`}>
              <input
                type="file"
                accept="video/mp4,.mp4"
                disabled={ingestDisabled}
                onChange={(e) => void onFileInput(e)}
              />
              Escolher vídeo local
            </label>
          </div>

          {uploading && (
            <>
              <div className="gallery-upload-progress">
                <p className="subtitle" style={{ margin: 0 }}>
                  {uploadLabel}
                </p>
                <button type="button" className="danger-button" onClick={cancelUpload}>
                  Cancelar envio
                </button>
              </div>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${Math.max(uploadProgress, uploadProgress > 0 ? 2 : 0)}%` }}
                />
              </div>
            </>
          )}

          <div style={{ marginTop: "1.25rem" }}>
            <label htmlFor="gallery-twitch-urls">URLs da Twitch (uma por linha)</label>
            {health?.yt_dlp === false && (
              <p className="warn" style={{ margin: "0.35rem 0 0.5rem" }}>
                yt-dlp não encontrado no servidor — instale para habilitar downloads.
              </p>
            )}
            <textarea
              id="gallery-twitch-urls"
              className="twitch-urls-input"
              rows={3}
              placeholder={"https://www.twitch.tv/videos/2783991554"}
              value={urlText}
              disabled={ingestDisabled || submitting || health?.yt_dlp === false}
              onChange={(e) => setUrlText(e.target.value)}
            />
            <button
              type="button"
              className="primary"
              style={{ marginTop: "0.75rem" }}
              disabled={ingestDisabled || submitting || !urlText.trim() || health?.yt_dlp === false}
              onClick={() => void onEnqueue()}
            >
              {submitting ? "Adicionando…" : "Adicionar à fila"}
            </button>
            <p className="subtitle" style={{ marginTop: "0.5rem", marginBottom: 0 }}>
              Até 2 downloads em paralelo; cada VOD usa fragmentos concorrentes (yt-dlp).
            </p>
          </div>
        </div>
      )}

      {(active.length > 0 || done.length > 0 || failed.length > 0) && (
        <div className="card gallery-section">
          <div className="twitch-queue-header">
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Fila de downloads</h2>
            <button type="button" className="link-btn" onClick={() => void refreshTwitch()}>
              Atualizar
            </button>
          </div>
          <ul className="twitch-download-list" role="list">
            {[...active, ...done, ...failed].map((d) => (
              <li key={d.id} className={`twitch-download-item status-${d.status}`}>
                <div className="twitch-download-meta">
                  <strong>
                    {statusLabel(d.status)}
                    {d.queue_position ? ` (#${d.queue_position} na fila)` : ""}
                  </strong>
                  <span className="file-path-hint">{d.url}</span>
                  {d.status === "failed" && (d.error || d.message) ? (
                    <span className="subtitle error-text">{d.error || d.message}</span>
                  ) : null}
                  {d.status !== "failed" && d.message ? (
                    <span className="subtitle">{d.message}</span>
                  ) : null}
                  {d.path && (
                    <span className="file-path-hint">
                      {d.filename} · {formatBytes(d.size_bytes)}
                    </span>
                  )}
                </div>
                {(d.status === "queued" || d.status === "downloading" || d.status === "running") && (
                  <div className="twitch-download-actions">
                    <div className="progress-bar" style={{ flex: 1, minWidth: 120 }}>
                      <div
                        className="progress-fill"
                        style={{ width: `${Math.min(100, d.percent)}%` }}
                      />
                    </div>
                    <button type="button" className="danger-button" onClick={() => void cancel(d.id)}>
                      Parar
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card gallery-section stored-vods">
        <div className="twitch-queue-header">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>
            VODs ({storedVods.length})
          </h2>
          <button type="button" className="link-btn" disabled={loading} onClick={() => void refresh()}>
            {loading ? "Atualizando…" : "Atualizar"}
          </button>
        </div>
        {storedVods.length === 0 ? (
          <p className="subtitle">Nenhum VOD armazenado ainda.</p>
        ) : (
          <ul className="stored-vods-list" role="list">
            {storedVods.map((v) => {
              const activeRow =
                pickMode && isMultiPick
                  ? multiPickPaths.includes(v.path)
                  : false;
              return (
                <li key={v.path}>
                  <div className={`stored-vod-row ${activeRow ? "active" : ""}`}>
                    {pickMode && isMultiPick && canPickVod ? (
                      <label className="stored-vod-pick" style={{ cursor: "pointer", flex: 1 }}>
                        <input
                          type="checkbox"
                          checked={multiPickPaths.includes(v.path)}
                          onChange={() => pickVod(v)}
                        />
                        <span>
                          <strong>{v.filename}</strong>
                          <span>
                            {" "}
                            · {formatBytes(v.size_bytes)} · {formatDate(v.modified)}
                          </span>
                        </span>
                      </label>
                    ) : (
                      <button
                        type="button"
                        className="stored-vod-pick"
                        onClick={() => pickVod(v)}
                        disabled={pickMode && !canPickVod}
                        title={v.path}
                      >
                        <strong>{v.filename}</strong>
                        <span>
                          {formatBytes(v.size_bytes)} · {formatDate(v.modified)}
                        </span>
                      </button>
                    )}
                    {!pickMode && (
                      <span className="stored-vod-actions">
                        <button
                          type="button"
                          className="link-btn stored-vod-delete"
                          onClick={() => void removeVod(v)}
                        >
                          Apagar
                        </button>
                      </span>
                    )}
                    {pickMode && !isMultiPick && canPickVod && (
                      <button type="button" className="browse-button" onClick={() => pickVod(v)}>
                        Selecionar
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="card gallery-section">
        <div className="twitch-queue-header">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>
            Clipes reutilizáveis ({pickableClips.length})
          </h2>
        </div>
        <p className="subtitle" style={{ marginTop: 0 }}>
          Clipes exportados que podem ser usados como entrada em outras features.
        </p>
        {pickableClips.length === 0 ? (
          <p className="subtitle">Nenhum clipe exportado ainda — use Gerar Reels.</p>
        ) : (
          <ul className="stored-vods-list" role="list">
            {pickableClips.map((clip) => {
              const fmt = clip.format === "reels" ? "Reels" : "YouTube";
              const activeRow = pickMode && isMultiPick && multiPickPaths.includes(clip.path);
              return (
                <li key={clip.path}>
                  <div className={`stored-vod-row ${activeRow ? "active" : ""}`}>
                    {pickMode && isMultiPick && canPickClip ? (
                      <label className="stored-vod-pick" style={{ cursor: "pointer", flex: 1 }}>
                        <input
                          type="checkbox"
                          checked={multiPickPaths.includes(clip.path)}
                          onChange={() => pickClip(clip)}
                        />
                        <span>
                          <strong>{clip.title}</strong>
                          <span>
                            {" "}
                            · {fmt} · {formatBytes(clip.size_bytes)}
                          </span>
                        </span>
                      </label>
                    ) : (
                      <button
                        type="button"
                        className="stored-vod-pick"
                        onClick={() => pickClip(clip)}
                        disabled={pickMode && !canPickClip}
                        title={clip.path}
                      >
                        <strong>{clip.title}</strong>
                        <span>
                          {fmt}
                          {clip.source_video ? ` · de ${clip.source_video}` : ""} ·{" "}
                          {formatBytes(clip.size_bytes)}
                        </span>
                      </button>
                    )}
                    {pickMode && !isMultiPick && canPickClip && (
                      <button type="button" className="browse-button" onClick={() => pickClip(clip)}>
                        Selecionar
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="card gallery-section reels-library">
        <div className="reels-library-header">
          <div>
            <h2 style={{ margin: "0 0 0.25rem", fontSize: "1.1rem" }}>Sessões exportadas</h2>
            <p className="subtitle" style={{ margin: 0 }}>
              Preview e download de clipes por sessão de exportação.
            </p>
          </div>
          <button type="button" onClick={() => void refresh()} disabled={loading || !apiReady}>
            {loading ? "Atualizando…" : "Atualizar"}
          </button>
        </div>

        {!loading && libraryJobs.length === 0 && (
          <p className="reels-library-empty">
            Nenhum reel exportado ainda — use <strong>Gerar Reels</strong>.
          </p>
        )}

        <ul className="reels-library-list">
          {libraryJobs.map((job) => {
            const isOpen = expandedJob === job.job_id;
            return (
              <li key={job.job_id} className="reels-library-item">
                <div className="reels-library-item-header">
                  <button
                    type="button"
                    className="reels-library-toggle"
                    onClick={() => setExpandedJob(isOpen ? null : job.job_id)}
                  >
                    <span className="reels-library-toggle-title">
                      {job.source_video || "Vídeo desconhecido"}
                    </span>
                    <span className="reels-library-toggle-meta">
                      {job.clip_count} clipe{job.clip_count === 1 ? "" : "s"} ·{" "}
                      {formatDate(job.modified)}
                    </span>
                  </button>
                  {!pickMode && (
                    <button
                      type="button"
                      className="danger-button"
                      disabled={deletingJob === job.job_id}
                      onClick={() => void handleDeleteJob(job.job_id, job.source_video)}
                    >
                      {deletingJob === job.job_id ? "Apagando…" : "Apagar sessão"}
                    </button>
                  )}
                </div>
                {isOpen && (
                  <div className="reels-library-expanded">
                    <ClipsGallery clips={job.clips} outputDir={job.output_dir} showDownload />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
