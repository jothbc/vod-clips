import { useCallback, useEffect, useRef, useState } from "react";
import { getApiDisplayLabel } from "../api/base";
import {
  deleteStoredVod,
  fetchPickableReelClips,
  fetchStoredVods,
  formatBytes,
  uploadVodWithProgress,
  type PickableReelClip,
  type StoredVod,
} from "../api/client";

type PickSource = "upload" | "stored" | "reel";

interface Props {
  value: string;
  valueSource?: PickSource | "";
  onChange: (path: string, source?: PickSource) => void;
  onNewFile?: () => void;
  disabled?: boolean;
  apiReady?: boolean;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

export default function FilePicker({
  value,
  valueSource = "",
  onChange,
  onNewFile,
  disabled,
  apiReady = true,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadAbortRef = useRef<(() => void) | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("");
  const [progressPercent, setProgressPercent] = useState(0);
  const [uploadLoaded, setUploadLoaded] = useState(0);
  const [uploadTotal, setUploadTotal] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [sizeLabel, setSizeLabel] = useState("");
  const [pickedSource, setPickedSource] = useState<PickSource | "">(valueSource);
  const [storedVods, setStoredVods] = useState<StoredVod[]>([]);
  const [vodsLoading, setVodsLoading] = useState(false);
  const [vodsError, setVodsError] = useState<string | null>(null);
  const [reelClips, setReelClips] = useState<PickableReelClip[]>([]);
  const [reelsLoading, setReelsLoading] = useState(false);
  const [reelsError, setReelsError] = useState<string | null>(null);

  const refreshStoredVods = useCallback(async () => {
    if (!apiReady) return;
    setVodsLoading(true);
    setVodsError(null);
    try {
      const data = await fetchStoredVods();
      setStoredVods(data.vods);
    } catch (e) {
      setVodsError(e instanceof Error ? e.message : String(e));
    } finally {
      setVodsLoading(false);
    }
  }, [apiReady]);

  const refreshReelClips = useCallback(async () => {
    if (!apiReady) return;
    setReelsLoading(true);
    setReelsError(null);
    try {
      const data = await fetchPickableReelClips();
      setReelClips(data.clips);
    } catch (e) {
      setReelsError(e instanceof Error ? e.message : String(e));
    } finally {
      setReelsLoading(false);
    }
  }, [apiReady]);

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshStoredVods(), refreshReelClips()]);
  }, [refreshStoredVods, refreshReelClips]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const resetSelection = () => {
    if (value) onNewFile?.();
    setError(null);
    setDisplayName("");
    setSizeLabel("");
  };

  const onFileInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    resetSelection();
    setDisplayName(file.name);
    setSizeLabel(formatSize(file.size));
    setBusy(true);
    setUploading(true);
    setBusyLabel("Enviando…");
    setProgressPercent(0);
    setUploadLoaded(0);
    setUploadTotal(file.size);

    try {
      const handle = uploadVodWithProgress(file, (loaded, total) => {
        setUploadLoaded(loaded);
        setUploadTotal(total);
        const denom = total ?? file.size;
        if (denom > 0) setProgressPercent((loaded / denom) * 100);
      });
      uploadAbortRef.current = handle.abort;
      const res = await handle.promise;
      setPickedSource("upload");
      onChange(res.path, "upload");
      void refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      onChange("");
      setDisplayName("");
      setSizeLabel("");
    } finally {
      uploadAbortRef.current = null;
      setBusy(false);
      setUploading(false);
      setBusyLabel("");
      setProgressPercent(0);
      setUploadLoaded(0);
      setUploadTotal(null);
      e.target.value = "";
    }
  };

  const cancelUpload = () => {
    uploadAbortRef.current?.();
    uploadAbortRef.current = null;
  };

  const pickStoredVod = (v: StoredVod) => {
    if (busy || disabled) return;
    resetSelection();
    setDisplayName(v.filename);
    setSizeLabel(formatSize(v.size_bytes));
    setPickedSource("stored");
    onChange(v.path, "stored");
  };

  const pickReelClip = (clip: PickableReelClip) => {
    if (busy || disabled) return;
    resetSelection();
    const fmtLabel = clip.format === "reels" ? "Reels 9:16" : "YouTube 16:9";
    setDisplayName(`${clip.title} (${fmtLabel})`);
    setSizeLabel(formatSize(clip.size_bytes));
    setPickedSource("reel");
    onChange(clip.path, "reel");
  };

  const formatClipLabel = (clip: PickableReelClip) => {
    const fmt = clip.format === "reels" ? "Reels" : "YouTube";
    const src = clip.source_video ? ` · de ${clip.source_video}` : "";
    return `${fmt}${src}`;
  };

  const removeStoredVod = async (v: StoredVod) => {
    if (busy || disabled) return;
    if (!confirm(`Remover ${v.filename} (${formatSize(v.size_bytes)})?`)) return;
    try {
      await deleteStoredVod(v.path);
      if (value === v.path) {
        onChange("");
        setDisplayName("");
        setSizeLabel("");
        setPickedSource("");
      }
      await refreshStoredVods();
    } catch (e) {
      setVodsError(e instanceof Error ? e.message : String(e));
    }
  };

  const pickerDisabled = disabled || busy || !apiReady;
  const progressLabel =
    uploadTotal && uploadTotal > 0 && busyLabel.startsWith("Enviando")
      ? `${busyLabel} ${progressPercent.toFixed(0)}% (${formatBytes(uploadLoaded)} / ${formatBytes(uploadTotal)})`
      : "";

  return (
    <div className="file-picker">
      <label className="file-picker-label">Vídeo (.mp4)</label>
      <p className="subtitle" style={{ margin: "0 0 0.75rem" }}>
        Envie um arquivo local, escolha um VOD em <code>temp/vods/</code> ou um clipe já exportado
        em <strong>Gerar Reels</strong>. Para baixar da Twitch, use a aba{" "}
        <strong>Baixar da Twitch</strong>.
      </p>

      {!apiReady && (
        <p className="warn" style={{ marginBottom: "0.75rem" }}>
          Aguardando API Python em <code>{getApiDisplayLabel()}</code>…
        </p>
      )}

      <div className="file-picker-row">
        <label className={`file-input-button ${pickerDisabled ? "disabled" : ""}`}>
          <input
            ref={inputRef}
            type="file"
            accept="video/mp4,.mp4"
            disabled={pickerDisabled}
            onChange={onFileInput}
          />
          Escolher vídeo local
        </label>
      </div>

      <div className="stored-vods" style={{ marginTop: "1rem" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "0.5rem",
          }}
        >
          <label style={{ margin: 0 }}>
            Vídeos já em <code>temp/vods/</code> ({storedVods.length})
          </label>
          <button
            type="button"
            className="link-btn"
            onClick={refreshStoredVods}
            disabled={vodsLoading || !apiReady}
          >
            {vodsLoading ? "Atualizando…" : "Atualizar"}
          </button>
        </div>
        {vodsError && <p className="error">{vodsError}</p>}
        {!vodsError && storedVods.length === 0 && (
          <p className="subtitle" style={{ marginTop: "0.35rem" }}>
            Nenhum vídeo armazenado ainda.
          </p>
        )}
        {storedVods.length > 0 && (
          <ul className="stored-vods-list" role="list">
            {storedVods.map((v) => {
              const active = value === v.path;
              return (
                <li key={v.path}>
                  <div className={`stored-vod-row ${active ? "active" : ""}`}>
                    <button
                      type="button"
                      className="stored-vod-pick"
                      onClick={() => pickStoredVod(v)}
                      disabled={pickerDisabled}
                      title={v.path}
                    >
                      <strong>{v.filename}</strong>
                      <span>
                        {formatBytes(v.size_bytes)} ·{" "}
                        {new Date(v.modified * 1000).toLocaleString()}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="link-btn stored-vod-delete"
                      onClick={() => removeStoredVod(v)}
                      disabled={pickerDisabled}
                      title="Apagar este arquivo"
                    >
                      Apagar
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="stored-vods" style={{ marginTop: "1rem" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "0.5rem",
          }}
        >
          <label style={{ margin: 0 }}>
            Clipes exportados — Reels gerados ({reelClips.length})
          </label>
          <button
            type="button"
            className="link-btn"
            onClick={refreshReelClips}
            disabled={reelsLoading || !apiReady}
          >
            {reelsLoading ? "Atualizando…" : "Atualizar"}
          </button>
        </div>
        {reelsError && <p className="error">{reelsError}</p>}
        {!reelsError && reelClips.length === 0 && (
          <p className="subtitle" style={{ marginTop: "0.35rem" }}>
            Nenhum clipe exportado ainda — use <strong>Gerar Reels</strong> e exporte highlights.
          </p>
        )}
        {reelClips.length > 0 && (
          <ul className="stored-vods-list" role="list">
            {reelClips.map((clip) => {
              const active = value === clip.path;
              return (
                <li key={clip.path}>
                  <div className={`stored-vod-row ${active ? "active" : ""}`}>
                    <button
                      type="button"
                      className="stored-vod-pick"
                      onClick={() => pickReelClip(clip)}
                      disabled={pickerDisabled}
                      title={clip.path}
                    >
                      <strong>{clip.title}</strong>
                      <span>
                        {formatClipLabel(clip)} · {formatBytes(clip.size_bytes)} ·{" "}
                        {new Date(clip.modified * 1000).toLocaleString()}
                      </span>
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {busy && uploading && (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "0.75rem",
              margin: "0.75rem 0 0.35rem",
            }}
          >
            <p className="subtitle" style={{ margin: 0 }}>
              {progressLabel}
            </p>
            <button type="button" className="danger-button" onClick={cancelUpload}>
              Cancelar envio
            </button>
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${Math.max(progressPercent, progressPercent > 0 ? 2 : 0)}%` }}
            />
          </div>
        </>
      )}

      {displayName && !busy && (
        <p className="file-selected">
          Pronto
          {pickedSource === "stored"
            ? " (temp/vods)"
            : pickedSource === "reel"
              ? " (clipe exportado)"
              : ""}
          : {displayName} ({sizeLabel})
        </p>
      )}

      {value && !busy && (
        <p className="file-path-hint" style={{ marginTop: "0.35rem" }}>
          Salvo em: {value}
        </p>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  );
}
