import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { fetchRelated, type VideoSummary } from "../../api/v2";
import { formatMmSs, formatRange } from "../../utils/timeFormat";
import AppHeader from "../components/AppHeader";
import ActionBar from "../components/ActionBar";
import CaptionsModal from "../components/CaptionsModal";
import CleanupModal from "../components/CleanupModal";
import FormatToggle, { type ClipFormat } from "../components/FormatToggle";
import GenerateClipsModal from "../components/GenerateClipsModal";
import TranscriptEditor from "../components/TranscriptEditor";
import TrimEditor from "../components/TrimEditor";
import WatchPlayer from "../components/WatchPlayer";
import { useVideo } from "../hooks/useVideo";
import "../v2.css";

function formatDuration(seconds: number): string {
  return formatMmSs(seconds);
}

function formatBadges(formats?: string[]): string {
  if (!formats?.length) return "";
  const labels = formats.map((f) => (f === "reels" ? "Mobile" : f === "youtube" ? "Desktop" : f));
  return labels.join(" · ");
}

function pickDefaultFormat(formats: string[], query: string | null): ClipFormat {
  if (query === "reels" && formats.includes("reels")) return "reels";
  if (query === "youtube" && formats.includes("youtube")) return "youtube";
  if (formats.includes("youtube")) return "youtube";
  if (formats.includes("reels")) return "reels";
  return "youtube";
}

export default function WatchPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { video, loading, error, refresh } = useVideo(id);
  const [related, setRelated] = useState<VideoSummary[]>([]);
  const [clipsModalOpen, setClipsModalOpen] = useState(false);
  const [captionsModalOpen, setCaptionsModalOpen] = useState(false);
  const [cleanupModalOpen, setCleanupModalOpen] = useState(false);
  const [trimMode, setTrimMode] = useState(false);
  const playerRef = useRef<HTMLVideoElement>(null);

  const clipFormats = video?.formats?.length ? video.formats : video?.format ? [video.format] : [];
  const [activeFormat, setActiveFormat] = useState<ClipFormat>("youtube");

  useEffect(() => {
    if (!video || video.kind !== "clip") return;
    setActiveFormat(pickDefaultFormat(clipFormats, searchParams.get("format")));
  }, [video?.id, video?.kind, clipFormats.join(","), searchParams]);

  const streamSrc = useMemo(() => {
    if (!video) return "";
    if (video.kind === "clip" && video.stream_urls) {
      return video.stream_urls[activeFormat] || video.stream_url;
    }
    return video.stream_url;
  }, [video, activeFormat]);

  const handleFormatChange = useCallback(
    (fmt: ClipFormat) => {
      setActiveFormat(fmt);
      const next = new URLSearchParams(searchParams);
      next.set("format", fmt);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const reloadRelated = useCallback(async () => {
    if (!id) return;
    try {
      const r = await fetchRelated(id);
      setRelated(r.items);
    } catch {
      setRelated([]);
    }
  }, [id]);

  useEffect(() => {
    void reloadRelated();
  }, [reloadRelated]);

  const seekTo = useCallback((t: number) => {
    const v = playerRef.current;
    if (v) {
      v.currentTime = t;
      v.play().catch(() => {});
    }
  }, []);

  const handleFeatureDone = useCallback(() => {
    void refresh();
    void reloadRelated();
    window.setTimeout(() => void reloadRelated(), 1000);
  }, [refresh, reloadRelated]);

  if (loading) {
    return (
      <div className="v2-root">
        <div className="v2-shell">
          <AppHeader />
          <p className="v2-loading">Carregando vídeo…</p>
        </div>
      </div>
    );
  }

  if (error || !video) {
    return (
      <div className="v2-root">
        <div className="v2-shell">
          <AppHeader />
          <p className="v2-error">{error || "Vídeo não encontrado"}</p>
          <Link to="/" className="v2-btn">
            Voltar
          </Link>
        </div>
      </div>
    );
  }

  const sidebarTitle = video.kind === "clip" ? "VOD original" : "Clipes deste VOD";
  const emptyMessage =
    video.kind === "clip" ? "VOD original não encontrado." : "Nenhum clipe gerado ainda.";

  return (
    <div className="v2-root">
      <div className="v2-shell">
        <AppHeader />
        <div className="v2-watch">
          <div>
            <WatchPlayer
              ref={playerRef}
              src={streamSrc}
              title={video.title}
              vertical={video.kind === "clip" && activeFormat === "reels"}
            />
            <div className="v2-watch-title-row">
              <h1 className="v2-watch-title">{video.title}</h1>
              {video.kind === "clip" && (
                <FormatToggle
                  formats={clipFormats}
                  active={activeFormat}
                  onChange={handleFormatChange}
                />
              )}
            </div>
            <p className="v2-card-meta">
              {video.duration > 0 ? formatDuration(video.duration) : ""}
              {video.size_bytes ? ` · ${(video.size_bytes / 1024 ** 2).toFixed(0)} MB` : ""}
            </p>
            <ActionBar
              video={video}
              onRefresh={refresh}
              onGenerateClips={() => setClipsModalOpen(true)}
              onOpenCaptions={() => setCaptionsModalOpen(true)}
              onOpenCleanup={() => setCleanupModalOpen(true)}
              trimMode={trimMode}
              onToggleTrim={() => setTrimMode((v) => !v)}
            />
            {trimMode && video.duration > 0 && (
              <TrimEditor
                video={video}
                duration={video.duration}
                playerRef={playerRef}
                sourceFormat={video.kind === "clip" ? activeFormat : undefined}
                onClose={() => setTrimMode(false)}
                onDone={() => {
                  setTrimMode(false);
                  handleFeatureDone();
                }}
              />
            )}
            {video.has_transcript && (
              <TranscriptEditor
                videoId={video.id}
                syncToParent={video.kind === "clip"}
                onSaved={refresh}
              />
            )}
          </div>
          <aside className="v2-sidebar">
            <p className="v2-sidebar-title">{sidebarTitle}</p>
            {related.length === 0 && <p className="v2-card-meta">{emptyMessage}</p>}
            {related.map((item) => (
              <Link key={item.id} to={`/watch/${item.id}`} className="v2-related-card">
                <div
                  className={`v2-related-thumb${
                    item.format === "reels" ? " v2-related-thumb--vertical" : ""
                  }`}
                >
                  <video src={item.stream_url} muted preload="metadata" />
                </div>
                <div>
                  <p className="v2-card-title" style={{ margin: 0 }}>
                    {item.title}
                  </p>
                  <p className="v2-card-meta">
                    {item.start != null && item.end != null
                      ? formatRange(item.start, item.end)
                      : item.duration > 0
                        ? formatDuration(item.duration)
                        : ""}
                    {formatBadges(item.formats) ? ` · ${formatBadges(item.formats)}` : ""}
                  </p>
                </div>
              </Link>
            ))}
          </aside>
        </div>
      </div>
      {clipsModalOpen && (
        <GenerateClipsModal
          video={video}
          playerRef={playerRef}
          onSeek={seekTo}
          onClose={() => setClipsModalOpen(false)}
          onDone={() => {
            setClipsModalOpen(false);
            handleFeatureDone();
          }}
        />
      )}
      {captionsModalOpen && (
        <CaptionsModal
          video={video}
          sourceFormat={video.kind === "clip" ? activeFormat : undefined}
          onClose={() => setCaptionsModalOpen(false)}
          onDone={() => {
            setCaptionsModalOpen(false);
            handleFeatureDone();
          }}
        />
      )}
      {cleanupModalOpen && (
        <CleanupModal
          video={video}
          sourceFormat={video.kind === "clip" ? activeFormat : undefined}
          onClose={() => setCleanupModalOpen(false)}
          onDone={() => {
            setCleanupModalOpen(false);
            handleFeatureDone();
          }}
        />
      )}
    </div>
  );
}
