import { useEffect, useState } from "react";
import { waitForApi } from "../../api/base";
import { fetchClips, type ClipSummary, type VideoSummary } from "../../api/v2";
import AppHeader from "../components/AppHeader";
import ClipCarousel from "../components/ClipCarousel";
import GalleryModal from "../components/GalleryModal";
import HorizontalRow from "../components/HorizontalRow";
import InfiniteFeed from "../components/InfiniteFeed";
import { useVideoFeed } from "../hooks/useVideoFeed";
import "../v2.css";

export default function HomePage() {
  const [apiReady, setApiReady] = useState(false);
  const [clips, setClips] = useState<ClipSummary[]>([]);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const { items, loading, hasMore, loadMore, refresh } = useVideoFeed();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await waitForApi();
        if (cancelled) return;
        setApiReady(true);
        const data = await fetchClips(12);
        if (!cancelled) setClips(data.clips);
      } catch {
        if (!cancelled) setApiReady(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const originals = items.filter((v) => v.kind === "original");

  function clipToSummary(c: ClipSummary): VideoSummary {
    return {
      id: c.id,
      title: c.title,
      kind: "clip",
      duration: c.duration,
      width: 0,
      height: 0,
      stream_url: c.stream_url,
      thumbnail_url: c.thumbnail_url,
      has_transcript: false,
      clip_count: 0,
      parent_id: c.parent_id,
      format: c.format,
    };
  }

  const mobileClips = clips.filter((c) => c.format === "reels").map(clipToSummary);
  const desktopClips = clips.filter((c) => c.format === "youtube").map(clipToSummary);

  return (
    <div className="v2-root">
      <div className="v2-shell">
        <AppHeader onOpenGallery={() => setGalleryOpen(true)} />
        <ClipCarousel clips={clips} />
        <HorizontalRow title="VODs originais" items={originals.slice(0, 12)} />
        <HorizontalRow title="Clipes mobile" items={mobileClips} vertical />
        <HorizontalRow title="Clipes desktop" items={desktopClips} />
        <InfiniteFeed
          items={items}
          hasMore={hasMore}
          loading={loading}
          onLoadMore={loadMore}
        />
      </div>
      <button
        type="button"
        className="v2-fab"
        onClick={() => setGalleryOpen(true)}
        aria-label="Abrir galeria"
        title="Galeria"
      >
        +
      </button>
      {galleryOpen && (
        <GalleryModal
          apiReady={apiReady}
          onClose={() => setGalleryOpen(false)}
          onChanged={() => {
            refresh();
            fetchClips(12).then((d) => setClips(d.clips)).catch(() => {});
          }}
        />
      )}
    </div>
  );
}
