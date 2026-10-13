import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useBay } from "../context/BayContext";

type SinkableMedia = HTMLVideoElement & {
  setSinkId: (sinkId: string) => Promise<void>;
  sinkId: string;
};

type MediaDevicesWithOutput = MediaDevices & {
  selectAudioOutput?: (options?: { deviceId?: string }) => Promise<MediaDeviceInfo>;
};

const SINK_STORAGE_KEY = "reels.audioSinkId";

function supportsSinkId(): boolean {
  return typeof HTMLMediaElement !== "undefined" && "setSinkId" in HTMLMediaElement.prototype;
}

function asSinkable(el: HTMLVideoElement | null): SinkableMedia | null {
  if (!el || typeof (el as SinkableMedia).setSinkId !== "function") return null;
  return el as SinkableMedia;
}

function deviceLabel(device: MediaDeviceInfo, index: number): string {
  const label = device.label?.trim();
  if (label) return label;
  if (!device.deviceId) return "Padrão do sistema";
  return `Saída de áudio ${index + 1}`;
}

function shortDeviceLabel(device: MediaDeviceInfo, index: number): string {
  const full = deviceLabel(device, index);
  // Drop trailing hardware ids like "(0dBc:0012)" for the narrow ops column.
  return full.replace(/\s*\([0-9a-fA-F]{2,}[:.][0-9a-fA-F].*$/, "").trim() || full;
}

async function unlockAudioOutputs(): Promise<MediaDeviceInfo | null> {
  const md = navigator.mediaDevices as MediaDevicesWithOutput | undefined;
  if (!md) return null;

  if (typeof md.selectAudioOutput === "function") {
    return md.selectAudioOutput();
  }

  const stream = await md.getUserMedia({ audio: true, video: false });
  for (const track of stream.getTracks()) track.stop();
  return null;
}

function readStoredSinkId(): string {
  try {
    return localStorage.getItem(SINK_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export default function AudioOutputControl() {
  const selectId = useId();
  const { getWatchVideo, hasWatchVideo } = useBay();
  const [supported] = useState(supportsSinkId);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [sinkId, setSinkId] = useState(readStoredSinkId);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const sinkIdRef = useRef(sinkId);
  sinkIdRef.current = sinkId;

  const refreshDevices = useCallback(async () => {
    if (!supported || !navigator.mediaDevices?.enumerateDevices) return [];
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      const outputs = all.filter((d) => d.kind === "audiooutput");
      setDevices(outputs);
      if (outputs.some((d) => d.deviceId && d.label?.trim())) {
        setUnlocked(true);
      }
      return outputs;
    } catch {
      return [];
    }
  }, [supported]);

  const applySinkId = useCallback(
    async (nextId: string) => {
      const video = asSinkable(getWatchVideo());
      setError(null);

      // Persist preference even before a player is ready.
      setSinkId(nextId);
      try {
        localStorage.setItem(SINK_STORAGE_KEY, nextId);
      } catch {
        /* ignore */
      }

      if (!video) return;

      setBusy(true);
      try {
        await video.setSinkId(nextId);
        await refreshDevices();
      } catch (e) {
        const name = e instanceof DOMException ? e.name : "";
        if (name === "NotAllowedError") {
          setError("Permissão necessária para trocar a saída.");
        } else if (name === "NotFoundError") {
          setError("Dispositivo não encontrado.");
          setSinkId("");
          try {
            localStorage.removeItem(SINK_STORAGE_KEY);
          } catch {
            /* ignore */
          }
        } else {
          setError(e instanceof Error ? e.message : "Falha ao alterar a saída.");
        }
      } finally {
        setBusy(false);
      }
    },
    [getWatchVideo, refreshDevices]
  );

  const requestOutputPermission = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const picked = await unlockAudioOutputs();
      const outputs = await refreshDevices();
      setUnlocked(true);
      if (picked?.deviceId) {
        await applySinkId(picked.deviceId);
      } else if (outputs.length <= 1) {
        setError("Ainda só a saída padrão. Aceite o prompt do navegador.");
      }
    } catch (e) {
      if (e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "AbortError")) {
        setError("Permissão cancelada ou bloqueada.");
      } else {
        setError(e instanceof Error ? e.message : "Falha ao listar saídas.");
      }
    } finally {
      setBusy(false);
    }
  }, [applySinkId, refreshDevices]);

  useEffect(() => {
    if (!supported) return;
    void refreshDevices();
    const onDeviceChange = () => {
      void refreshDevices();
    };
    navigator.mediaDevices?.addEventListener?.("devicechange", onDeviceChange);
    return () => {
      navigator.mediaDevices?.removeEventListener?.("devicechange", onDeviceChange);
    };
  }, [supported, refreshDevices]);

  // Re-apply preferred sink when a watch video mounts.
  useEffect(() => {
    if (!supported || !hasWatchVideo) return;
    const preferred = sinkIdRef.current;
    const video = asSinkable(getWatchVideo());
    if (!video) return;
    if ((video.sinkId || "") === preferred) return;
    void applySinkId(preferred);
  }, [supported, hasWatchVideo, getWatchVideo, applySinkId]);

  if (!supported) return null;

  const labeledCount = devices.filter((d) => d.label?.trim()).length;
  const needsUnlock = !unlocked && labeledCount <= 1;
  const currentLabel =
    devices.find((d) => d.deviceId === sinkId)?.label?.trim() ||
    (sinkId ? "Saída salva" : "Padrão do sistema");

  return (
    <div className="v2-audio-output v2-audio-output--ops">
      <div className="v2-audio-output-head">
        <span className="v2-audio-output-label" id={`${selectId}-label`}>
          Saída de áudio
        </span>
        {!hasWatchVideo && <span className="v2-audio-output-badge">sem player</span>}
      </div>
      <p className="v2-audio-output-current" title={currentLabel}>
        {currentLabel}
      </p>
      <select
        id={selectId}
        className="v2-audio-output-select"
        aria-labelledby={`${selectId}-label`}
        value={sinkId}
        disabled={busy}
        onChange={(e) => {
          void applySinkId(e.target.value);
        }}
        onFocus={() => {
          void refreshDevices();
        }}
      >
        <option value="">Padrão do sistema</option>
        {sinkId && !devices.some((d) => d.deviceId === sinkId) && (
          <option value={sinkId}>Saída salva</option>
        )}
        {devices
          .filter((d) => d.deviceId)
          .map((device, index) => (
            <option key={device.deviceId} value={device.deviceId}>
              {shortDeviceLabel(device, index)}
            </option>
          ))}
      </select>
      <button
        type="button"
        className={`v2-btn v2-btn--sm${needsUnlock ? " v2-btn--primary" : ""}`}
        disabled={busy}
        onClick={() => {
          void requestOutputPermission();
        }}
        title="O Chrome só lista todas as saídas depois de uma permissão do usuário"
      >
        {needsUnlock ? "Liberar saídas…" : "Escolher outra…"}
      </button>
      {needsUnlock && (
        <p className="v2-audio-output-hint">
          O navegador oculta as saídas até você liberar permissão.
        </p>
      )}
      {error && <p className="v2-audio-output-error">{error}</p>}
    </div>
  );
}
