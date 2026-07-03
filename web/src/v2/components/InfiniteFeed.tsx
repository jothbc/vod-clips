import { useCallback, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { VideoSummary } from "../../api/v2";

interface Props {
  items: VideoSummary[];
  hasMore: boolean;
  loading: boolean;
  onLoadMore: () => void;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function InfiniteFeed({ items, hasMore, loading, onLoadMore }: Props) {
  const sentinelRef = useRef<HTMLDivElement>(null);

  const handleIntersect = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      if (entries[0]?.isIntersecting && hasMore && !loading) {
        onLoadMore();
      }
    },
    [hasMore, loading, onLoadMore]
  );

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(handleIntersect, { rootMargin: "200px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [handleIntersect]);

  if (!items.length && !loading) {
    return null;
  }

  return (
    <section className="v2-section">
      <div className="v2-section-header">
        <h2 className="v2-section-title">Biblioteca</h2>
      </div>
      <div className="v2-row" style={{ flexWrap: "wrap", overflowX: "visible" }}>
        {items.map((item) => (
          <Link key={item.id} to={`/watch/${item.id}`} className="v2-card">
            <div className="v2-card-thumb">
              <video src={item.stream_url} muted preload="metadata" />
            </div>
            <div className="v2-card-body">
              <p className="v2-card-title">{item.title}</p>
              <p className="v2-card-meta">
                {item.duration > 0 ? formatDuration(item.duration) : "—"}
              </p>
            </div>
          </Link>
        ))}
      </div>
      <div ref={sentinelRef} className="v2-loading">
        {loading ? "Carregando…" : hasMore ? "" : "Fim da lista"}
      </div>
    </section>
  );
}
