import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "../api/base";
import type { HighlightItem } from "../api/client";

interface Props {
  jobId: string;
  highlights: HighlightItem[];
  sourceVideoUrl: string;
  previewWarning?: string | null;
  selected: Set<number>;
  onSelectedChange: (next: Set<number>) => void;
  onPreview: (index: number) => void;
  activeIndex: number | null;
  disabled?: boolean;
}

export default function HighlightsReview({
  highlights,
  sourceVideoUrl,
  previewWarning,
  selected,
  onSelectedChange,
  onPreview,
  activeIndex,
  disabled,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const segmentRef = useRef<{ start: number; end: number } | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  /** Lazy: avoid mounting <video src=10GB VOD> until the user picks a highlight. */
  const [videoSrc, setVideoSrc] = useState<string | null>(null);

  const active =
    activeIndex !== null && activeIndex >= 0 && activeIndex < highlights.length
      ? highlights[activeIndex]
      : null;

  const ensureVideoMounted = useCallback(() => {
    if (!sourceVideoUrl) return;
    const url = apiUrl(sourceVideoUrl);
    setVideoSrc((prev) => (prev === url ? prev : url));
  }, [sourceVideoUrl]);

  const seekToSegment = useCallback(
    (hl: HighlightItem, autoplay = true) => {
      const video = videoRef.current;
      if (!video) return;
      setLoadError(null);
      segmentRef.current = { start: hl.start, end: hl.end };

      const runSeek = () => {
        try {
          video.currentTime = hl.start;
          if (autoplay) void video.play().catch(() => {});
        } catch {
          setLoadError("Could not seek in preview video.");
        }
      };

      if (video.readyState >= 1) {
        runSeek();
      } else {
        video.addEventListener("loadedmetadata", runSeek, { once: true });
      }
    },
    []
  );

  useEffect(() => {
    if (activeIndex === null) return;
    ensureVideoMounted();
  }, [activeIndex, ensureVideoMounted]);

  useEffect(() => {
    if (active && videoSrc) seekToSegment(active);
  }, [active, videoSrc, seekToSegment]);

  const onTimeUpdate = () => {
    const video = videoRef.current;
    const seg = segmentRef.current;
    if (!video || !seg) return;
    if (video.currentTime >= seg.end - 0.05) {
      video.pause();
      video.currentTime = seg.start;
      setPlaying(false);
    }
  };

  const onRowPreview = (index: number) => {
    ensureVideoMounted();
    onPreview(index);
  };

  const toggleSelect = (index: number) => {
    const next = new Set(selected);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    onSelectedChange(next);
  };

  const selectAll = () => {
    onSelectedChange(new Set(highlights.map((_, i) => i)));
  };

  const selectNone = () => {
    onSelectedChange(new Set());
  };

  if (!highlights.length) {
    return (
      <div className="card">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Highlights</h2>
        <p className="subtitle" style={{ marginBottom: 0 }}>
          No highlights detected for this VOD.
        </p>
      </div>
    );
  }

  return (
    <div className="card highlights-review">
      <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.1rem" }}>Review highlights</h2>
      <p className="subtitle" style={{ marginBottom: "1rem" }}>
        Click a row to load preview and jump to that segment. Export still cuts from the
        original file on disk.
      </p>
      {previewWarning && (
        <p className="subtitle" style={{ marginBottom: "1rem", color: "var(--warn, #c9a227)" }}>
          {previewWarning}
        </p>
      )}

      <div className="highlights-layout">
        <div className="highlights-list-wrap">
          <div className="highlights-toolbar">
            <button type="button" className="link-btn" onClick={selectAll} disabled={disabled}>
              Select all
            </button>
            <span className="toolbar-sep">·</span>
            <button type="button" className="link-btn" onClick={selectNone} disabled={disabled}>
              Clear
            </button>
            <span className="toolbar-count">
              {selected.size} / {highlights.length} selected
            </span>
          </div>

          <ul className="highlights-list" role="list">
            {highlights.map((hl) => (
              <li key={hl.index}>
                <div
                  className={`highlight-row ${activeIndex === hl.index ? "active" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => onRowPreview(hl.index)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onRowPreview(hl.index);
                    }
                  }}
                >
                  <label
                    className="highlight-check"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(hl.index)}
                      disabled={disabled}
                      onChange={() => toggleSelect(hl.index)}
                    />
                  </label>
                  <div className="highlight-info">
                    <strong>{hl.title}</strong>
                    <span>
                      {formatTime(hl.start)} – {formatTime(hl.end)} · score {hl.score.toFixed(2)} ·{" "}
                      {hl.source}
                    </span>
                    {hl.reason && <span className="highlight-reason">{hl.reason}</span>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="highlights-player-wrap">
          <p className="subtitle" style={{ margin: "0 0 0.5rem" }}>
            {active ? (
              <>
                Preview: {active.title} ({formatTime(active.start)} – {formatTime(active.end)})
              </>
            ) : (
              "Select a highlight to load preview"
            )}
          </p>
          {videoSrc ? (
            <video
              ref={videoRef}
              className="source-preview"
              controls
              preload="metadata"
              playsInline
              src={videoSrc}
              onTimeUpdate={onTimeUpdate}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onError={() =>
                setLoadError(
                  "Preview failed to load. Large VODs may need proxy.make_preview: true in config, or wait and retry."
                )
              }
            />
          ) : (
            <div
              className="source-preview source-preview-placeholder"
              style={{
                aspectRatio: "16 / 9",
                background: "var(--surface-2, #1a1a1a)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                borderRadius: 8,
              }}
            >
              <span className="subtitle">Click a highlight to start preview</span>
            </div>
          )}
          {loadError && <p className="error">{loadError}</p>}
          {active && videoSrc && (
            <button
              type="button"
              className="browse-button"
              style={{ marginTop: "0.5rem" }}
              disabled={disabled}
              onClick={() => seekToSegment(active, !playing)}
            >
              {playing ? "Replay segment" : "Play segment"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
