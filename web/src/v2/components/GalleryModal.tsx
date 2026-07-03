import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { TwitchDownloadState } from "../../api/client";
import { useTwitchDownloadQueue } from "../../hooks/useTwitchDownloadQueue";
import { deleteVideo, fetchGallery, uploadVideoV2, type GalleryVideo } from "../../api/v2";

interface Props {
  apiReady: boolean;
  onClose: () => void;
  onChanged: () => void;
}

type PendingDelete = {
  id: string;
  title: string;
  kind: "vod" | "clip";
  clipCount?: number;
};

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V7h12Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DeleteConfirm({
  label,
  busy,
  onConfirm,
  onCancel,
}: {
  label: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="v2-gallery-confirm" onClick={(e) => e.stopPropagation()}>
      <span className="v2-gallery-confirm-label" title={label}>
        {label}
      </span>
      <button type="button" className="v2-btn v2-btn--ghost" disabled={busy} onClick={onCancel}>
        Cancelar
      </button>
      <button type="button" className="v2-btn v2-btn--danger" disabled={busy} onClick={onConfirm}>
        {busy ? "…" : "Excluir"}
      </button>
    </div>
  );
}

function twitchStatusLabel(status: string): string {
  switch (status) {
    case "queued":
      return "Na fila";
    case "downloading":
    case "running":
      return "Baixando";
    case "completed":
      return "Concluído";
    case "failed":
      return "Falhou";
    case "cancelled":
      return "Cancelado";
    default:
      return status;
  }
}

function isActiveTwitchStatus(status: string): boolean {
  return status === "queued" || status === "downloading" || status === "running";
}

function twitchErrorText(d: TwitchDownloadState): string {
  return (d.error || d.message || "").trim();
}

function TwitchDownloadItem({
  download,
  onCancel,
}: {
  download: TwitchDownloadState;
  onCancel: (id: string) => void;
}) {
  const active = isActiveTwitchStatus(download.status);
  const failed = download.status === "failed";
  const detail = twitchErrorText(download);

  return (
    <li className={`v2-twitch-item v2-twitch-item--${download.status}`}>
      <div className="v2-twitch-item-head">
        <span className={`v2-twitch-badge v2-twitch-badge--${download.status}`}>
          {twitchStatusLabel(download.status)}
        </span>
        {download.video_id ? (
          <span className="v2-twitch-vod-id">VOD {download.video_id}</span>
        ) : null}
        {active && download.percent > 0 ? (
          <span className="v2-twitch-percent">{download.percent.toFixed(0)}%</span>
        ) : null}
        {active ? (
          <button
            type="button"
            className="v2-btn v2-btn--ghost v2-twitch-cancel"
            onClick={() => onCancel(download.id)}
          >
            Cancelar
          </button>
        ) : null}
      </div>
      <a className="v2-twitch-url" href={download.url} target="_blank" rel="noreferrer">
        {download.url}
      </a>
      {failed && detail ? (
        <pre className="v2-twitch-error" title={detail}>
          {detail}
        </pre>
      ) : null}
      {!failed && detail && download.status !== "completed" ? (
        <p className="v2-twitch-hint">{detail.length > 140 ? `${detail.slice(0, 140)}…` : detail}</p>
      ) : null}
    </li>
  );
}

export default function GalleryModal({ apiReady, onClose, onChanged }: Props) {
  const [videos, setVideos] = useState<GalleryVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [urlText, setUrlText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleting, setDeleting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const hadActiveDownloads = useRef(false);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = opts?.silent ?? false;
    if (!silent) {
      setLoading(true);
    }
    setError(null);
    try {
      const data = await fetchGallery();
      setVideos(data.videos);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar galeria");
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  const handleDownloadCompleted = useCallback(
    (state: TwitchDownloadState) => {
      void load({ silent: true });
      onChanged();
      if (state.video_id) {
        setExpanded((prev) => {
          const next = new Set(prev);
          next.add(`twitch_${state.video_id}`);
          return next;
        });
      }
    },
    [load, onChanged],
  );

  const { downloads, error: twitchQueueError, submitting, enqueueUrls, cancel, refresh: refreshTwitch } =
    useTwitchDownloadQueue(apiReady, { onDownloadCompleted: handleDownloadCompleted });

  useEffect(() => {
    if (apiReady) void load();
  }, [apiReady, load]);

  const hasActiveDownloads = downloads.some((d) => isActiveTwitchStatus(d.status));

  useEffect(() => {
    if (!apiReady || !hasActiveDownloads) return;
    const timer = setInterval(() => {
      refreshTwitch();
      void load({ silent: true });
    }, 3000);
    return () => clearInterval(timer);
  }, [apiReady, hasActiveDownloads, refreshTwitch, load]);

  // Refresh library when the last active download finishes (covers missed SSE events).
  useEffect(() => {
    if (hadActiveDownloads.current && !hasActiveDownloads) {
      void load({ silent: true });
      onChanged();
    }
    hadActiveDownloads.current = hasActiveDownloads;
  }, [hasActiveDownloads, load, onChanged]);

  const prevDownloadStatus = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    for (const d of downloads) {
      const prev = prevDownloadStatus.current.get(d.id);
      if (d.status === "completed" && prev !== "completed") {
        void load({ silent: true });
        onChanged();
      }
      prevDownloadStatus.current.set(d.id, d.status);
    }
  }, [downloads, load, onChanged]);

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function requestDelete(item: PendingDelete) {
    setPendingDelete(item);
    setError(null);
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteVideo(pendingDelete.id);
      if (pendingDelete.kind === "vod") {
        setExpanded((prev) => {
          const next = new Set(prev);
          next.delete(pendingDelete.id);
          return next;
        });
      }
      setPendingDelete(null);
      onChanged();
      await load({ silent: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao excluir");
    } finally {
      setDeleting(false);
    }
  }

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadProgress(0);
    setError(null);
    try {
      await uploadVideoV2(file, (loaded, total) => setUploadProgress(Math.round((loaded / total) * 100)));
      onChanged();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload falhou");
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  }

  async function handleTwitchEnqueue() {
    const urls = urlText
      .split(/[\n,]+/)
      .map((u) => u.trim())
      .filter(Boolean);
    if (!urls.length) return;
    await enqueueUrls(urls);
    setUrlText("");
    refreshTwitch();
  }

  return (
    <div className="v2-modal-backdrop" onClick={onClose}>
      <div className="v2-modal" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <h2>Galeria</h2>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <div className="v2-modal-body">
          {error && <p className="v2-error">{error}</p>}

          <section style={{ marginBottom: 20 }}>
            <h3 className="v2-section-title" style={{ fontSize: "0.95rem" }}>
              Upload
            </h3>
            <input
              ref={fileRef}
              type="file"
              accept="video/mp4"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleUpload(f);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              className="v2-btn v2-btn--primary"
              disabled={uploading || !apiReady}
              onClick={() => fileRef.current?.click()}
            >
              {uploading ? `Enviando ${uploadProgress}%` : "Selecionar .mp4"}
            </button>
          </section>

          <section style={{ marginBottom: 20 }}>
            <h3 className="v2-section-title" style={{ fontSize: "0.95rem" }}>
              Twitch VOD
            </h3>
            <textarea
              value={urlText}
              onChange={(e) => setUrlText(e.target.value)}
              placeholder="https://www.twitch.tv/videos/…"
              rows={2}
              style={{
                width: "100%",
                padding: 8,
                borderRadius: 8,
                border: "1px solid var(--v2-border)",
                background: "var(--v2-bg)",
                color: "var(--v2-text)",
                fontFamily: "inherit",
                marginBottom: 8,
              }}
            />
            <button
              type="button"
              className="v2-btn"
              disabled={submitting || !apiReady}
              onClick={handleTwitchEnqueue}
            >
              {submitting ? "Enfileirando…" : "Baixar"}
            </button>
            {twitchQueueError && <p className="v2-error">{twitchQueueError}</p>}
            {downloads.length > 0 && (
              <ul className="v2-twitch-queue">
                {downloads.slice(0, 8).map((d) => (
                  <TwitchDownloadItem key={d.id} download={d} onCancel={cancel} />
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3 className="v2-section-title" style={{ fontSize: "0.95rem" }}>
              Biblioteca
            </h3>
            {loading ? (
              <p className="v2-loading">Carregando…</p>
            ) : videos.length === 0 ? (
              <p className="v2-empty">Nenhum vídeo ainda.</p>
            ) : (
              <ul className="v2-gallery-tree">
                {videos.map((v) => (
                  <li key={v.id} className="v2-gallery-item">
                    <div className="v2-gallery-item-header">
                      <div className="v2-gallery-item-main" onClick={() => toggleExpand(v.id)}>
                        <span>{expanded.has(v.id) ? "▼" : "▶"}</span>
                        <Link to={`/watch/${v.id}`} onClick={(e) => e.stopPropagation()}>
                          {v.title}
                        </Link>
                        <span className="v2-card-meta">
                          {v.clip_count} clip{v.clip_count !== 1 ? "s" : ""}
                        </span>
                      </div>
                      <div className="v2-gallery-actions">
                        {pendingDelete?.id === v.id ? (
                          <DeleteConfirm
                            label={
                              v.clip_count > 0
                                ? `VOD + ${v.clip_count} clip${v.clip_count !== 1 ? "s" : ""}`
                                : "VOD"
                            }
                            busy={deleting}
                            onConfirm={confirmDelete}
                            onCancel={() => setPendingDelete(null)}
                          />
                        ) : (
                          <button
                            type="button"
                            className="v2-gallery-delete"
                            title="Excluir VOD e todos os clips"
                            aria-label={`Excluir ${v.title}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              requestDelete({
                                id: v.id,
                                title: v.title,
                                kind: "vod",
                                clipCount: v.clip_count,
                              });
                            }}
                          >
                            <TrashIcon />
                          </button>
                        )}
                      </div>
                    </div>
                    {expanded.has(v.id) && v.clips.length > 0 && (
                      <ul className="v2-gallery-children">
                        {v.clips.map((c) => (
                          <li key={c.id} className="v2-gallery-child">
                            <div className="v2-gallery-child-main">
                              <Link to={`/watch/${c.id}`}>{c.title}</Link>
                              {c.formats.map((fmt) => (
                                <Link
                                  key={fmt}
                                  to={`/watch/${c.id}?format=${fmt}`}
                                  className="v2-format-icon"
                                  title={fmt === "reels" ? "Mobile" : "Desktop"}
                                >
                                  {fmt === "reels" ? "📱" : "🖥"}
                                </Link>
                              ))}
                            </div>
                            <div className="v2-gallery-actions">
                              {pendingDelete?.id === c.id ? (
                                <DeleteConfirm
                                  label="Clip"
                                  busy={deleting}
                                  onConfirm={confirmDelete}
                                  onCancel={() => setPendingDelete(null)}
                                />
                              ) : (
                                <button
                                  type="button"
                                  className="v2-gallery-delete"
                                  title="Excluir clip"
                                  aria-label={`Excluir ${c.title}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    requestDelete({ id: c.id, title: c.title, kind: "clip" });
                                  }}
                                >
                                  <TrashIcon />
                                </button>
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
