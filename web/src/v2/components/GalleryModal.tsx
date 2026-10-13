import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { TwitchDownloadState } from "../../api/v2";
import { useTwitchDownloadQueue } from "../../hooks/useTwitchDownloadQueue";
import { deleteVideo, fetchGallery, renameVideo, uploadVideoV2, type GalleryVideo } from "../../api/v2";
import { queryKeys } from "../../queryClient";
import { useBay } from "../context/BayContext";

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

type PendingRename = {
  id: string;
  title: string;
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

function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5Z"
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

function RenameEditor({
  value,
  busy,
  onChange,
  onConfirm,
  onCancel,
}: {
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  return (
    <form
      className="v2-gallery-rename"
      onClick={(e) => e.stopPropagation()}
      onSubmit={(e) => {
        e.preventDefault();
        onConfirm();
      }}
    >
      <input
        ref={inputRef}
        className="v2-gallery-rename-input"
        value={value}
        disabled={busy}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
        }}
        aria-label="Novo título"
      />
      <button type="button" className="v2-btn v2-btn--ghost" disabled={busy} onClick={onCancel}>
        Cancelar
      </button>
      <button type="submit" className="v2-btn v2-btn--primary" disabled={busy || !value.trim()}>
        {busy ? "…" : "Salvar"}
      </button>
    </form>
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

function playbackUsesVideo(src: string, videoId: string): boolean {
  let decoded = videoId;
  try {
    decoded = decodeURIComponent(videoId);
  } catch {
    decoded = videoId;
  }
  if (decoded.includes("::")) {
    const [parent, clip] = decoded.split("::", 2);
    return src.includes(`/media/${parent}/clips/${clip}/`);
  }
  return src.includes(`/media/${decoded}/`);
}

function releasePlayback(videoId: string, getWatchVideo: () => HTMLVideoElement | null): boolean {
  const el = getWatchVideo();
  if (!el) return false;
  const src = el.currentSrc || el.src || "";
  if (!playbackUsesVideo(src, videoId)) return false;
  el.pause();
  el.removeAttribute("src");
  el.load();
  return true;
}

function decodeJsonEscapes(value: string): string {
  return value.replace(/\\u([0-9a-fA-F]{4})/g, (_, hex: string) =>
    String.fromCharCode(Number.parseInt(hex, 16)),
  );
}

function humanizeTwitchError(raw: string): string {
  const decoded = decodeJsonEscapes(raw.trim());
  const start = decoded.indexOf("{");
  const end = decoded.lastIndexOf("}");
  if (start >= 0 && end > start) {
    try {
      const parsed = JSON.parse(decoded.slice(start, end + 1)) as {
        error?: { code?: string; message?: string } | string;
        message?: string;
      };
      const err = parsed.error;
      const message =
        (typeof err === "object" && err?.message ? err.message : "") ||
        (typeof parsed.message === "string" ? parsed.message : "");
      const code = typeof err === "object" ? err?.code : "";
      if (code === "NOT_FOUND" || /n[aã]o encontrado/i.test(message)) {
        return "VOD não encontrado na Twitch. Ele pode ter sido apagado ou o link expirou.";
      }
      if (message.trim()) return message.trim();
    } catch {
      // Fall through to the decoded text.
    }
  }
  return decoded;
}

function twitchErrorText(d: TwitchDownloadState): string {
  return humanizeTwitchError(d.error || d.message || "");
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
  const queryClient = useQueryClient();
  const { getWatchVideo } = useBay();
  const [actionError, setActionError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [urlText, setUrlText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [pendingRename, setPendingRename] = useState<PendingRename | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renaming, setRenaming] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const hadActiveDownloads = useRef(false);
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  const galleryQuery = useQuery({
    queryKey: queryKeys.gallery,
    queryFn: fetchGallery,
    enabled: apiReady,
    staleTime: 5_000,
  });

  const videos: GalleryVideo[] = galleryQuery.data?.videos ?? [];
  const loading = galleryQuery.isLoading;
  const error =
    actionError ??
    (galleryQuery.error instanceof Error ? galleryQuery.error.message : null);

  const invalidateGallery = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.gallery });
    onChangedRef.current();
  }, [queryClient]);

  const handleDownloadCompleted = useCallback(
    (state: TwitchDownloadState) => {
      void invalidateGallery();
      if (state.video_id) {
        setExpanded((prev) => {
          const next = new Set(prev);
          next.add(`twitch_${state.video_id}`);
          return next;
        });
      }
    },
    [invalidateGallery],
  );

  const { downloads, error: twitchQueueError, submitting, enqueueUrls, cancel, refresh: refreshTwitch } =
    useTwitchDownloadQueue(apiReady, { onDownloadCompleted: handleDownloadCompleted });

  const hasActiveDownloads = downloads.some((d) => isActiveTwitchStatus(d.status));

  // When the last active download finishes, refresh library once (SSE may already have fired).
  useEffect(() => {
    if (hadActiveDownloads.current && !hasActiveDownloads) {
      void invalidateGallery();
    }
    hadActiveDownloads.current = hasActiveDownloads;
  }, [hasActiveDownloads, invalidateGallery]);

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function requestDelete(item: PendingDelete) {
    setPendingRename(null);
    setPendingDelete(item);
    setActionError(null);
  }

  function requestRename(item: PendingRename) {
    setPendingDelete(null);
    setPendingRename(item);
    setRenameDraft(item.title);
    setActionError(null);
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    setActionError(null);
    try {
      const released = releasePlayback(pendingDelete.id, getWatchVideo);
      if (released) {
        await new Promise((resolve) => window.setTimeout(resolve, 400));
      }
      await deleteVideo(pendingDelete.id);
      if (pendingDelete.kind === "vod") {
        setExpanded((prev) => {
          const next = new Set(prev);
          next.delete(pendingDelete.id);
          return next;
        });
      }
      setPendingDelete(null);
      await invalidateGallery();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Erro ao excluir");
    } finally {
      setDeleting(false);
    }
  }

  async function confirmRename() {
    if (!pendingRename) return;
    const title = renameDraft.trim();
    if (!title || title === pendingRename.title) {
      setPendingRename(null);
      return;
    }
    setRenaming(true);
    setActionError(null);
    try {
      await renameVideo(pendingRename.id, { title });
      setPendingRename(null);
      await invalidateGallery();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Erro ao renomear");
    } finally {
      setRenaming(false);
    }
  }

  function renderRowActions(item: { id: string; title: string }, deleteMeta: PendingDelete) {
    if (pendingRename?.id === item.id) {
      return (
        <RenameEditor
          value={renameDraft}
          busy={renaming}
          onChange={setRenameDraft}
          onConfirm={() => void confirmRename()}
          onCancel={() => setPendingRename(null)}
        />
      );
    }
    if (pendingDelete?.id === item.id) {
      return (
        <DeleteConfirm
          label={
            deleteMeta.kind === "vod"
              ? deleteMeta.clipCount && deleteMeta.clipCount > 0
                ? `VOD + ${deleteMeta.clipCount} clip${deleteMeta.clipCount !== 1 ? "s" : ""}`
                : "VOD"
              : "Clip"
          }
          busy={deleting}
          onConfirm={confirmDelete}
          onCancel={() => setPendingDelete(null)}
        />
      );
    }
    return (
      <>
        <button
          type="button"
          className="v2-gallery-icon-btn"
          title="Renomear"
          aria-label={`Renomear ${item.title}`}
          onClick={(e) => {
            e.stopPropagation();
            requestRename({ id: item.id, title: item.title });
          }}
        >
          <PencilIcon />
        </button>
        <button
          type="button"
          className="v2-gallery-icon-btn v2-gallery-icon-btn--danger"
          title={deleteMeta.kind === "vod" ? "Excluir VOD e todos os clips" : "Excluir clip"}
          aria-label={`Excluir ${item.title}`}
          onClick={(e) => {
            e.stopPropagation();
            requestDelete(deleteMeta);
          }}
        >
          <TrashIcon />
        </button>
      </>
    );
  }

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadProgress(0);
    setActionError(null);
    try {
      await uploadVideoV2(file, (loaded, total) => setUploadProgress(Math.round((loaded / total) * 100)));
      await invalidateGallery();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Upload falhou");
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
    void refreshTwitch();
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
                        {renderRowActions(
                          { id: v.id, title: v.title },
                          { id: v.id, title: v.title, kind: "vod", clipCount: v.clip_count },
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
                              {renderRowActions(
                                { id: c.id, title: c.title },
                                { id: c.id, title: c.title, kind: "clip" },
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
