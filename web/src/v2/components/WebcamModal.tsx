import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  clearWebcamRegion,
  saveWebcamRegion,
  videoFrameUrl,
  type VideoDetail,
} from "../../api/v2";
import { formatMmSs } from "../../utils/timeFormat";

interface Props {
  video: VideoDetail;
  playerRef: RefObject<HTMLVideoElement | null>;
  onClose: () => void;
  onSaved: () => void;
}

type Bbox = { x1: number; y1: number; x2: number; y2: number };

type DragMode = "move" | "nw" | "ne" | "sw" | "se" | null;

const MIN_SIZE = 24;

function defaultBox(w: number, h: number): Bbox {
  const bw = Math.round(w * 0.22);
  const bh = Math.round(h * 0.22);
  return {
    x1: Math.max(0, w - bw - Math.round(w * 0.02)),
    y1: Math.max(0, h - bh - Math.round(h * 0.02)),
    x2: Math.min(w, w - Math.round(w * 0.02)),
    y2: Math.min(h, h - Math.round(h * 0.02)),
  };
}

function clampBox(box: Bbox, w: number, h: number): Bbox {
  let x1 = Math.round(box.x1);
  let y1 = Math.round(box.y1);
  let x2 = Math.round(box.x2);
  let y2 = Math.round(box.y2);
  x1 = Math.max(0, Math.min(x1, w - MIN_SIZE));
  y1 = Math.max(0, Math.min(y1, h - MIN_SIZE));
  x2 = Math.max(x1 + MIN_SIZE, Math.min(x2, w));
  y2 = Math.max(y1 + MIN_SIZE, Math.min(y2, h));
  return { x1, y1, x2, y2 };
}

function scaleBbox(box: Bbox, fromW: number, fromH: number, toW: number, toH: number): Bbox {
  if (fromW <= 0 || fromH <= 0 || (fromW === toW && fromH === toH)) {
    return box;
  }
  return clampBox(
    {
      x1: (box.x1 * toW) / fromW,
      y1: (box.y1 * toH) / fromH,
      x2: (box.x2 * toW) / fromW,
      y2: (box.y2 * toH) / fromH,
    },
    toW,
    toH
  );
}

export default function WebcamModal({ video, playerRef, onClose, onSaved }: Props) {
  const vw = video.desktop_frame_width || video.width || 1920;
  const vh = video.desktop_frame_height || video.height || 1080;
  const [frameAt, setFrameAt] = useState(() => {
    const saved = video.webcam_region?.frame_at;
    if (saved && saved > 0) return saved;
    const t = playerRef.current?.currentTime;
    if (t && t > 0) return t;
    return Math.max(0, video.duration * 0.3);
  });
  const [frameKey, setFrameKey] = useState(0);
  const [box, setBox] = useState<Bbox>(() => {
    const r = video.webcam_region;
    const fw = video.desktop_frame_width || video.width || 1920;
    const fh = video.desktop_frame_height || video.height || 1080;
    if (r) {
      return scaleBbox(
        { x1: r.x1, y1: r.y1, x2: r.x2, y2: r.y2 },
        r.source_width || fw,
        r.source_height || fh,
        fw,
        fh
      );
    }
    return defaultBox(fw, fh);
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    mode: DragMode;
    startX: number;
    startY: number;
    startBox: Bbox;
  } | null>(null);

  useEffect(() => {
    const r = video.webcam_region;
    const fw = video.desktop_frame_width || video.width || 1920;
    const fh = video.desktop_frame_height || video.height || 1080;
    if (r) {
      setBox(
        scaleBbox(
          { x1: r.x1, y1: r.y1, x2: r.x2, y2: r.y2 },
          r.source_width || fw,
          r.source_height || fh,
          fw,
          fh
        )
      );
    }
  }, [video.webcam_region, video.desktop_frame_width, video.desktop_frame_height, video.width, video.height]);

  const layout = useCallback(() => {
    const stage = stageRef.current;
    if (!stage) return null;
    const rect = stage.getBoundingClientRect();
    const scale = Math.min(rect.width / vw, rect.height / vh);
    const dispW = vw * scale;
    const dispH = vh * scale;
    const offX = (rect.width - dispW) / 2;
    const offY = (rect.height - dispH) / 2;
    return { rect, scale, offX, offY, dispW, dispH };
  }, [vw, vh]);

  const onPointerDown = (e: React.PointerEvent, mode: DragMode) => {
    e.preventDefault();
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = { mode, startX: e.clientX, startY: e.clientY, startBox: { ...box } };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || !d.mode) return;
    const L = layout();
    if (!L) return;
    const dx = (e.clientX - d.startX) / L.scale;
    const dy = (e.clientY - d.startY) / L.scale;
    const b = d.startBox;
    let next = { ...b };
    if (d.mode === "move") {
      const w = b.x2 - b.x1;
      const h = b.y2 - b.y1;
      let x1 = b.x1 + dx;
      let y1 = b.y1 + dy;
      x1 = Math.max(0, Math.min(x1, vw - w));
      y1 = Math.max(0, Math.min(y1, vh - h));
      next = { x1, y1, x2: x1 + w, y2: y1 + h };
    } else if (d.mode === "nw") {
      next = { x1: b.x1 + dx, y1: b.y1 + dy, x2: b.x2, y2: b.y2 };
    } else if (d.mode === "ne") {
      next = { x1: b.x1, y1: b.y1 + dy, x2: b.x2 + dx, y2: b.y2 };
    } else if (d.mode === "sw") {
      next = { x1: b.x1 + dx, y1: b.y1, x2: b.x2, y2: b.y2 + dy };
    } else if (d.mode === "se") {
      next = { x1: b.x1, y1: b.y1, x2: b.x2 + dx, y2: b.y2 + dy };
    }
    setBox(clampBox(next, vw, vh));
  };

  const onPointerUp = () => {
    dragRef.current = null;
  };

  const displayBox = useCallback(() => {
    const L = layout();
    if (!L) return { left: 0, top: 0, width: 0, height: 0 };
    return {
      left: L.offX + box.x1 * L.scale,
      top: L.offY + box.y1 * L.scale,
      width: (box.x2 - box.x1) * L.scale,
      height: (box.y2 - box.y1) * L.scale,
    };
  }, [box, layout]);

  const db = displayBox();
  const frameSrc = videoFrameUrl(video.id, frameAt, frameKey);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await saveWebcamRegion(video.id, {
        x1: Math.round(box.x1),
        y1: Math.round(box.y1),
        x2: Math.round(box.x2),
        y2: Math.round(box.y2),
        frame_at: frameAt,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    setSaving(true);
    setError(null);
    try {
      await clearWebcamRegion(video.id);
      setBox(defaultBox(vw, vh));
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao limpar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="v2-modal-backdrop" onClick={onClose}>
      <div className="v2-modal v2-modal--wide v2-webcam-modal" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <div>
            <h2>Webcam</h2>
            <p className="v2-publish-sub">Marque a região da webcam no frame desktop</p>
          </div>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        <div className="v2-modal-body">
          {error && <p className="v2-error">{error}</p>}

          <div className="v2-webcam-time">
            <label>
              Frame em {formatMmSs(frameAt)}
              <input
                type="range"
                min={0}
                max={Math.max(0.1, video.duration - 0.1)}
                step={0.1}
                value={frameAt}
                onChange={(e) => setFrameAt(parseFloat(e.target.value))}
                onMouseUp={() => setFrameKey((k) => k + 1)}
                onTouchEnd={() => setFrameKey((k) => k + 1)}
              />
            </label>
            <button type="button" className="v2-btn v2-btn--ghost" onClick={() => setFrameKey((k) => k + 1)}>
              Atualizar frame
            </button>
          </div>

          <div
            className="v2-webcam-stage"
            ref={stageRef}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerUp}
          >
            <img src={frameSrc} alt="Frame do vídeo" className="v2-webcam-frame" draggable={false} />
            <div
              className="v2-webcam-roi"
              style={{ left: db.left, top: db.top, width: db.width, height: db.height }}
              onPointerDown={(e) => onPointerDown(e, "move")}
            >
              <span className="v2-webcam-roi__label">webcam</span>
              {(["nw", "ne", "sw", "se"] as const).map((h) => (
                <span
                  key={h}
                  className={`v2-webcam-handle v2-webcam-handle--${h}`}
                  onPointerDown={(e) => onPointerDown(e, h)}
                />
              ))}
            </div>
          </div>

          <div className="v2-webcam-readout" aria-live="polite">
            <span>
              frame {vw}×{vh}
            </span>
            <span>x1 {Math.round(box.x1)}</span>
            <span>y1 {Math.round(box.y1)}</span>
            <span>x2 {Math.round(box.x2)}</span>
            <span>y2 {Math.round(box.y2)}</span>
            <span>
              {Math.round(box.x2 - box.x1)}×{Math.round(box.y2 - box.y1)} px
            </span>
          </div>

          <div className="v2-modal-actions">
            <button type="button" className="v2-btn" disabled={saving} onClick={() => void handleClear()}>
              Limpar região
            </button>
            <button
              type="button"
              className="v2-btn v2-btn--primary"
              disabled={saving}
              onClick={() => void handleSave()}
            >
              {saving ? "Salvando…" : "Salvar região"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
