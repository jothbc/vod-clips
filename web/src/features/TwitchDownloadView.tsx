import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteStoredVod,
  fetchStoredVods,
  formatBytes,
  type StoredVod,
} from "../api/client";
import { useTwitchDownloadQueue } from "../hooks/useTwitchDownloadQueue";

const PENDING_VOD_KEY = "reels_pending_vod_path";

interface Props {
  apiReady: boolean;
  health: { ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null;
  onUseVod: (feature: "reels" | "cleanup", path: string) => void;
}

function statusLabel(status: string): string {
  switch (status) {
    case "queued":
      return "Na fila";
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

export default function TwitchDownloadView({ apiReady, health, onUseVod }: Props) {
  const [urlText, setUrlText] = useState("");
  const [storedVods, setStoredVods] = useState<StoredVod[]>([]);
  const [vodsLoading, setVodsLoading] = useState(false);

  const { downloads, error, submitting, enqueueUrls, cancel, refresh } =
    useTwitchDownloadQueue(apiReady);

  const refreshStoredVods = useCallback(async () => {
    if (!apiReady) return;
    setVodsLoading(true);
    try {
      const data = await fetchStoredVods();
      setStoredVods(data.vods);
    } catch {
      /* ignore */
    } finally {
      setVodsLoading(false);
    }
  }, [apiReady]);

  const onEnqueue = async () => {
    const urls = urlText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (!urls.length) return;
    await enqueueUrls(urls);
    setUrlText("");
    void refreshStoredVods();
  };

  useEffect(() => {
    void refreshStoredVods();
  }, [refreshStoredVods]);

  const prevCompletedRef = useRef(0);
  useEffect(() => {
    const n = downloads.filter((d) => d.status === "completed").length;
    if (n > prevCompletedRef.current) {
      void refreshStoredVods();
    }
    prevCompletedRef.current = n;
  }, [downloads, refreshStoredVods]);

  const active = downloads.filter((d) => d.status === "queued" || d.status === "running");
  const done = downloads.filter((d) => d.status === "completed");
  const failed = downloads.filter(
    (d) => d.status === "failed" || d.status === "cancelled"
  );

  const useVod = (path: string, feature: "reels" | "cleanup") => {
    localStorage.setItem(PENDING_VOD_KEY, path);
    onUseVod(feature, path);
  };

  return (
    <>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.1rem" }}>Baixar VODs da Twitch</h2>
        <p className="subtitle" style={{ marginBottom: "1rem" }}>
          Cole uma ou mais URLs (uma por linha). Até 2 downloads em paralelo. Arquivos vão para{" "}
          <code>temp/vods</code>.
        </p>

        {health?.yt_dlp === false && (
          <p className="warn" style={{ marginBottom: "0.75rem" }}>
            yt-dlp não encontrado no servidor — instale para habilitar downloads.
          </p>
        )}

        <label htmlFor="twitch-urls">URLs dos VODs</label>
        <textarea
          id="twitch-urls"
          className="twitch-urls-input"
          rows={4}
          placeholder={"https://www.twitch.tv/videos/2783991554\nhttps://www.twitch.tv/videos/1234567890"}
          value={urlText}
          disabled={!apiReady || submitting || health?.yt_dlp === false}
          onChange={(e) => setUrlText(e.target.value)}
        />
        <button
          type="button"
          className="primary"
          style={{ marginTop: "0.75rem" }}
          disabled={!apiReady || submitting || !urlText.trim() || health?.yt_dlp === false}
          onClick={() => void onEnqueue()}
        >
          {submitting ? "Adicionando…" : "Adicionar à fila"}
        </button>
      </div>

      {(active.length > 0 || done.length > 0 || failed.length > 0) && (
        <div className="card">
          <div className="twitch-queue-header">
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Fila de downloads</h2>
            <button type="button" className="link-btn" onClick={() => void refresh()}>
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
                  {d.message && <span className="subtitle">{d.message}</span>}
                  {d.path && (
                    <span className="file-path-hint">
                      {d.filename} · {formatBytes(d.size_bytes)}
                    </span>
                  )}
                </div>
                {(d.status === "queued" || d.status === "running") && (
                  <div className="twitch-download-actions">
                    <div className="progress-bar" style={{ flex: 1, minWidth: 120 }}>
                      <div
                        className="progress-fill"
                        style={{ width: `${Math.min(100, d.percent)}%` }}
                      />
                    </div>
                    <button
                      type="button"
                      className="danger-button"
                      onClick={() => void cancel(d.id)}
                    >
                      Parar
                    </button>
                  </div>
                )}
                {d.status === "completed" && d.path && (
                  <div className="twitch-download-actions">
                    <button
                      type="button"
                      className="browse-button"
                      onClick={() => useVod(d.path, "reels")}
                    >
                      Usar em Gerar Reels
                    </button>
                    <button
                      type="button"
                      className="browse-button"
                      onClick={() => useVod(d.path, "cleanup")}
                    >
                      Usar em Limpar vídeo
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card stored-vods">
        <div className="twitch-queue-header">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Vídeos em temp/vods</h2>
          <button
            type="button"
            className="link-btn"
            disabled={vodsLoading}
            onClick={() => void refreshStoredVods()}
          >
            {vodsLoading ? "Atualizando…" : "Atualizar"}
          </button>
        </div>
        {storedVods.length === 0 ? (
          <p className="subtitle">Nenhum VOD salvo ainda.</p>
        ) : (
          <ul className="stored-vods-list" role="list">
            {storedVods.map((v) => (
              <li key={v.path}>
                <div className="stored-vod-row">
                  <span>
                    <strong>{v.filename}</strong>
                    <span className="subtitle">
                      {" "}
                      · {formatBytes(v.size_bytes)}
                    </span>
                  </span>
                  <span className="stored-vod-actions">
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => useVod(v.path, "reels")}
                    >
                      Reels
                    </button>
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => useVod(v.path, "cleanup")}
                    >
                      Limpar
                    </button>
                    <button
                      type="button"
                      className="link-btn stored-vod-delete"
                      onClick={async () => {
                        if (!confirm(`Apagar ${v.filename}?`)) return;
                        await deleteStoredVod(v.path);
                        void refreshStoredVods();
                      }}
                    >
                      Apagar
                    </button>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

export { PENDING_VOD_KEY };
