import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchPickableReelClips,
  fetchStoredVods,
  formatBytes,
  type PickableReelClip,
  type StoredVod,
} from "../api/client";

export type MultiPickEntry = {
  path: string;
  label: string;
  source: "vod" | "reel";
  size_bytes?: number;
};

interface Props {
  value: string[];
  onChange: (paths: string[]) => void;
  disabled?: boolean;
  apiReady?: boolean;
}

export default function VideoMultiPicker({ value, onChange, disabled, apiReady = true }: Props) {
  const [storedVods, setStoredVods] = useState<StoredVod[]>([]);
  const [reelClips, setReelClips] = useState<PickableReelClip[]>([]);
  const [vodsLoading, setVodsLoading] = useState(false);
  const [reelsLoading, setReelsLoading] = useState(false);
  const [vodsError, setVodsError] = useState<string | null>(null);
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

  const allEntries = useMemo<MultiPickEntry[]>(() => {
    const vods: MultiPickEntry[] = storedVods.map((v) => ({
      path: v.path,
      label: v.filename,
      source: "vod" as const,
      size_bytes: v.size_bytes,
    }));
    const reels: MultiPickEntry[] = reelClips.map((c) => ({
      path: c.path,
      label: c.title || c.path.split("/").pop() || c.path,
      source: "reel" as const,
      size_bytes: c.size_bytes,
    }));
    return [...vods, ...reels];
  }, [storedVods, reelClips]);

  const selectedSet = useMemo(() => new Set(value), [value]);

  const toggle = (path: string) => {
    if (disabled) return;
    if (selectedSet.has(path)) {
      onChange(value.filter((p) => p !== path));
    } else {
      onChange([...value, path]);
    }
  };

  const selectAll = () => {
    if (disabled) return;
    onChange(allEntries.map((e) => e.path));
  };

  const clearAll = () => {
    if (disabled) return;
    onChange([]);
  };

  const pickerDisabled = disabled || !apiReady;

  return (
    <div className="card">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.5rem",
          flexWrap: "wrap",
        }}
      >
        <strong>Selecionar vídeos ({value.length} marcado{value.length === 1 ? "" : "s"})</strong>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button type="button" className="link-btn" onClick={selectAll} disabled={pickerDisabled}>
            Selecionar todos
          </button>
          <button type="button" className="link-btn" onClick={clearAll} disabled={pickerDisabled}>
            Limpar
          </button>
          <button type="button" className="link-btn" onClick={refreshAll} disabled={pickerDisabled}>
            {vodsLoading || reelsLoading ? "Atualizando…" : "Atualizar"}
          </button>
        </div>
      </div>

      {(vodsError || reelsError) && (
        <p className="error" style={{ marginTop: "0.5rem" }}>
          {vodsError || reelsError}
        </p>
      )}

      <div className="stored-vods" style={{ marginTop: "1rem" }}>
        <label style={{ margin: 0 }}>VODs em temp/vods/ ({storedVods.length})</label>
        {storedVods.length === 0 && !vodsLoading && (
          <p className="subtitle" style={{ marginTop: "0.35rem" }}>
            Nenhum VOD armazenado.
          </p>
        )}
        {storedVods.length > 0 && (
          <ul className="stored-vods-list" role="list">
            {storedVods.map((v) => (
              <li key={v.path}>
                <label className={`stored-vod-row ${selectedSet.has(v.path) ? "active" : ""}`}>
                  <input
                    type="checkbox"
                    checked={selectedSet.has(v.path)}
                    onChange={() => toggle(v.path)}
                    disabled={pickerDisabled}
                  />
                  <span className="stored-vod-pick" style={{ cursor: "pointer" }}>
                    <strong>{v.filename}</strong>
                    <span>
                      {formatBytes(v.size_bytes)} · {new Date(v.modified * 1000).toLocaleString()}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="stored-vods" style={{ marginTop: "1rem" }}>
        <label style={{ margin: 0 }}>Clipes exportados — Reels gerados ({reelClips.length})</label>
        {reelClips.length === 0 && !reelsLoading && (
          <p className="subtitle" style={{ marginTop: "0.35rem" }}>
            Nenhum clipe exportado ainda.
          </p>
        )}
        {reelClips.length > 0 && (
          <ul className="stored-vods-list" role="list">
            {reelClips.map((clip) => (
              <li key={clip.path}>
                <label className={`stored-vod-row ${selectedSet.has(clip.path) ? "active" : ""}`}>
                  <input
                    type="checkbox"
                    checked={selectedSet.has(clip.path)}
                    onChange={() => toggle(clip.path)}
                    disabled={pickerDisabled}
                  />
                  <span className="stored-vod-pick" style={{ cursor: "pointer" }}>
                    <strong>{clip.title}</strong>
                    <span>
                      {clip.format} · {formatBytes(clip.size_bytes)}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
