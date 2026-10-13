import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { postTransformReel } from "../../api/v2";
import type { JobState } from "../../api/jobs";
import { formatMmSs } from "../../utils/timeFormat";
import ActionBar from "../components/ActionBar";
import CaptionsModal from "../components/CaptionsModal";
import PublishModal from "../components/PublishModal";
import CleanupModal from "../components/CleanupModal";
import FormatToggle, { type ClipFormat } from "../components/FormatToggle";
import CreateClipModal from "../components/CreateClipModal";
import JobProgressBar from "../components/JobProgressBar";
import TransformReelModal from "../components/TransformReelModal";
import TrimEditor from "../components/TrimEditor";
import WatchPlayer from "../components/WatchPlayer";
import WebcamModal from "../components/WebcamModal";
import { useBay } from "../context/BayContext";
import { useVideo } from "../hooks/useVideo";
import { useV2Job } from "../hooks/useV2Job";

function formatDuration(seconds: number): string {
  return formatMmSs(seconds);
}

function formatSizeBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) {
    const mb = bytes / 1024 ** 2;
    return mb >= 100 ? `${mb.toFixed(0)} MB` : `${mb.toFixed(1)} MB`;
  }
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
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
  const { setOpenPublish, setCanPublish, refreshMedia } = useBay();
  const [createClipModalOpen, setCreateClipModalOpen] = useState(false);
  const [captionsModalOpen, setCaptionsModalOpen] = useState(false);
  const [cleanupModalOpen, setCleanupModalOpen] = useState(false);
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [webcamModalOpen, setWebcamModalOpen] = useState(false);
  const [transformModalOpen, setTransformModalOpen] = useState(false);
  const [trimMode, setTrimMode] = useState(false);
  const [transformMessage, setTransformMessage] = useState<string | null>(null);
  const [transformClipId, setTransformClipId] = useState("");
  const playerRef = useRef<HTMLVideoElement>(null);

  const clipFormats = video?.formats?.length ? video.formats : video?.format ? [video.format] : [];
  const [activeFormat, setActiveFormat] = useState<ClipFormat>("youtube");

  useEffect(() => {
    if (!video || video.kind !== "clip") return;
    setActiveFormat(pickDefaultFormat(clipFormats, searchParams.get("format")));
  }, [video?.id, video?.kind, clipFormats.join(","), searchParams]);

  const optimisticSrc = useMemo(() => {
    if (!id || id.includes("::")) return "";
    return `/api/v2/media/${encodeURIComponent(id)}/source.mp4`;
  }, [id]);

  const streamSrc = useMemo(() => {
    if (video) {
      if (video.kind === "clip" && video.stream_urls) {
        return video.stream_urls[activeFormat] || video.stream_url;
      }
      return video.stream_url || optimisticSrc;
    }
    return optimisticSrc;
  }, [video, activeFormat, optimisticSrc]);

  const handleFormatChange = useCallback(
    (fmt: ClipFormat) => {
      setActiveFormat(fmt);
      const next = new URLSearchParams(searchParams);
      next.set("format", fmt);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const handleFeatureDone = useCallback(() => {
    void refresh();
    refreshMedia();
  }, [refresh, refreshMedia]);

  useEffect(() => {
    if (video) {
      setCanPublish(true);
      setOpenPublish(() => {
        setPublishModalOpen(true);
      });
    } else {
      setCanPublish(false);
      setOpenPublish(null);
    }
    return () => {
      setCanPublish(false);
      setOpenPublish(null);
    };
  }, [video, setCanPublish, setOpenPublish]);

  const onTransformCompleted = useCallback(
    (job: JobState) => {
      const clipId = job.result_clip_id || job.result_video_id || "";
      setTransformClipId(clipId);
      setTransformMessage("Reel salvo na galeria.");
      handleFeatureDone();
    },
    [handleFeatureDone]
  );

  const {
    job: transformJob,
    error: transformError,
    running: transformRunning,
    waitForJob: waitForTransformJob,
    cancel: cancelTransformJob,
  } = useV2Job({
    onCompleted: onTransformCompleted,
    onFailed: () => setTransformMessage("Falha ao transformar em reel"),
  });

  const canTransformReel = useMemo(() => {
    if (!video) return false;
    const isDesktopClip =
      video.kind === "clip" &&
      activeFormat === "youtube" &&
      (video.formats?.includes("youtube") ?? video.format === "youtube");
    const isLandscapeVod =
      video.kind === "original" &&
      video.width > 0 &&
      video.height > 0 &&
      video.width >= video.height;
    return isDesktopClip || isLandscapeVod;
  }, [video, activeFormat]);

  const canWebcam = useMemo(() => {
    if (!video) return false;
    if (video.webcam_eligible) return true;
    const isDesktopClip =
      video.kind === "clip" &&
      (video.formats?.includes("youtube") ?? video.format === "youtube");
    const isLandscapeVod =
      video.kind === "original" &&
      video.width > 0 &&
      video.height > 0 &&
      video.width >= video.height;
    return isDesktopClip || isLandscapeVod;
  }, [video]);

  const hasWebcamRegion = Boolean(video?.has_webcam_region);

  const handleTransformReel = useCallback(
    async (includeWebcam: boolean) => {
      if (!video || transformRunning) return;
      setTransformMessage(null);
      setTransformClipId("");
      setTransformModalOpen(false);
      try {
        const res = await postTransformReel(video.id, { include_webcam: includeWebcam });
        waitForTransformJob(res.job_id);
      } catch (e) {
        setTransformMessage(e instanceof Error ? e.message : "Erro ao iniciar transformação");
      }
    },
    [video, transformRunning, waitForTransformJob]
  );

  if (error && !video && !loading) {
    return (
      <div className="v2-bay-canvas-body">
        <p className="v2-error">{error || "Vídeo não encontrado"}</p>
        <Link to="/" className="v2-btn">
          Voltar
        </Link>
      </div>
    );
  }

  return (
    <div className="v2-bay-canvas-body">
      <WatchPlayer
        ref={playerRef}
        src={streamSrc}
        title={video?.title || "Carregando…"}
        vertical={video?.kind === "clip" && activeFormat === "reels"}
      />
      {!trimMode && (
        <>
          <div className="v2-watch-title-row">
            <h1 className="v2-watch-title">{video?.title || (loading ? "Carregando…" : id)}</h1>
            {video?.kind === "clip" && (
              <FormatToggle formats={clipFormats} active={activeFormat} onChange={handleFormatChange} />
            )}
          </div>
          <p className="v2-card-meta">
            {video && video.duration > 0 ? formatDuration(video.duration) : loading ? "…" : ""}
            {video?.size_bytes ? ` · ${formatSizeBytes(video.size_bytes)}` : ""}
          </p>
          {video ? (
            <ActionBar
              video={video}
              onRefresh={refresh}
              onGenerateClip={() => setCreateClipModalOpen(true)}
              onOpenCaptions={() => setCaptionsModalOpen(true)}
              onOpenCleanup={() => setCleanupModalOpen(true)}
              onOpenPublish={() => setPublishModalOpen(true)}
              onOpenWebcam={() => {
                void refresh();
                setWebcamModalOpen(true);
              }}
              canWebcam={canWebcam}
              trimMode={trimMode}
              onToggleTrim={() => setTrimMode((v) => !v)}
              canTransformReel={canTransformReel}
              transformBusy={transformRunning}
              onTransformReel={() => setTransformModalOpen(true)}
            />
          ) : (
            <p className="v2-loading">Carregando detalhes…</p>
          )}
          {(transformRunning || transformJob) && (
            <div className="v2-trim-processing">
              <JobProgressBar job={transformJob} onCancel={cancelTransformJob} />
            </div>
          )}
          {(transformMessage || transformError) && (
            <p className="v2-card-meta">
              {transformError || transformMessage}
              {transformClipId && (
                <>
                  {" "}
                  <Link to={`/watch/${transformClipId}?format=reels`}>Abrir reel</Link>
                </>
              )}
            </p>
          )}
        </>
      )}
      {trimMode && video && video.duration > 0 && (
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
      {createClipModalOpen && video && (
        <CreateClipModal
          video={video}
          playerRef={playerRef}
          streamSrc={streamSrc}
          onClose={() => setCreateClipModalOpen(false)}
          onDone={() => {
            setCreateClipModalOpen(false);
            handleFeatureDone();
          }}
        />
      )}
      {captionsModalOpen && video && (
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
      {cleanupModalOpen && video && (
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
      {publishModalOpen && video && (
        <PublishModal
          video={video}
          sourceFormat={video.kind === "clip" ? activeFormat : undefined}
          onClose={() => setPublishModalOpen(false)}
        />
      )}
      {webcamModalOpen && video && (
        <WebcamModal
          video={video}
          playerRef={playerRef}
          onClose={() => setWebcamModalOpen(false)}
          onSaved={() => {
            void refresh();
            setWebcamModalOpen(false);
          }}
        />
      )}
      {transformModalOpen && (
        <TransformReelModal
          hasWebcamRegion={hasWebcamRegion}
          busy={transformRunning}
          onClose={() => setTransformModalOpen(false)}
          onChoose={(includeWebcam) => void handleTransformReel(includeWebcam)}
        />
      )}
    </div>
  );
}
