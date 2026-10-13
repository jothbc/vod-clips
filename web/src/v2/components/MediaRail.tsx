import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { searchVideos, type VideoSummary } from "../../api/v2";
import { waitForApi } from "../../api/base";
import { useBay } from "../context/BayContext";
import { useVideoFeed } from "../hooks/useVideoFeed";
import { formatMmSs } from "../../utils/timeFormat";

type RailFilter = "all" | "vod" | "clips";

function formatDuration(seconds: number): string {
  if (seconds <= 0) return "—";
  return formatMmSs(seconds);
}

function kindLabel(item: VideoSummary): string {
  if (item.kind === "original") return "vod";
  if (item.format === "reels") return "clip · mobile";
  if (item.format === "youtube") return "clip · desktop";
  return "clip";
}

export default function MediaRail() {
  const { id: selectedId } = useParams<{ id?: string }>();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const searchQuery = location.pathname === "/search" ? (searchParams.get("q")?.trim() ?? "") : "";
  const isSearch = Boolean(searchQuery);

  const [filter, setFilter] = useState<RailFilter>("all");
  const { items, loading, error, hasMore, loadMore, refresh } = useVideoFeed();
  const [searchResults, setSearchResults] = useState<VideoSummary[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const { setRefreshMedia, closeDrawers, railOpen } = useBay();

  useEffect(() => {
    setRefreshMedia(() => {
      refresh();
    });
    return () => setRefreshMedia(null);
  }, [refresh, setRefreshMedia]);

  useEffect(() => {
    if (!isSearch) {
      setSearchResults([]);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setSearchLoading(true);
      setSearchError(null);
      try {
        await waitForApi();
        const data = await searchVideos(searchQuery);
        if (!cancelled) setSearchResults(data.videos);
      } catch (e) {
        if (!cancelled) {
          setSearchError(e instanceof Error ? e.message : "Erro na busca");
          setSearchResults([]);
        }
      } finally {
        if (!cancelled) setSearchLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isSearch, searchQuery]);

  const sourceItems = isSearch ? searchResults : items;

  const filtered = useMemo(() => {
    if (filter === "vod") return sourceItems.filter((v) => v.kind === "original");
    if (filter === "clips") return sourceItems.filter((v) => v.kind === "clip");
    return sourceItems;
  }, [sourceItems, filter]);

  const handleIntersect = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      if (isSearch) return;
      if (entries[0]?.isIntersecting && hasMore && !loading) loadMore();
    },
    [hasMore, loading, loadMore, isSearch]
  );

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || isSearch) return;
    const obs = new IntersectionObserver(handleIntersect, { rootMargin: "120px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [handleIntersect, isSearch]);

  const busy = isSearch ? searchLoading : loading;
  const err = isSearch ? searchError : error;

  return (
    <aside className={`v2-bay-rail${railOpen ? " v2-bay-rail--open" : ""}`} aria-label="Lista de mídia">
      <div className="v2-bay-pane-h">
        <span>Media</span>
        <small>{isSearch ? `busca` : "rail"}</small>
      </div>
      {isSearch && (
        <p className="v2-bay-rail-search-label">
          Resultados para &ldquo;{searchQuery}&rdquo;
        </p>
      )}
      <div className="v2-bay-filters" role="tablist" aria-label="Filtro de mídia">
        {(
          [
            ["all", "all"],
            ["vod", "vod"],
            ["clips", "clips"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={filter === key}
            className={`v2-bay-chip${filter === key ? " v2-bay-chip--on" : ""}`}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="v2-bay-rail-list">
        {err && <p className="v2-error">{err}</p>}
        {!busy && !err && filtered.length === 0 && (
          <p className="v2-card-meta">{isSearch ? "Nenhum resultado." : "Nenhuma mídia ainda."}</p>
        )}
        {filtered.map((item) => {
          const active = selectedId === item.id;
          return (
            <Link
              key={item.id}
              to={`/watch/${encodeURIComponent(item.id)}`}
              className={`v2-bay-rail-item${active ? " v2-bay-rail-item--on" : ""}`}
              onClick={closeDrawers}
            >
              <div className="v2-bay-rail-thumb" aria-hidden>
                {item.format === "reels" ? "9:16" : "16:9"}
              </div>
              <div className="v2-bay-rail-meta">
                <span className="v2-bay-rail-title">{item.title}</span>
                <span className="v2-bay-rail-sub">
                  {kindLabel(item)} · {formatDuration(item.duration)}
                </span>
              </div>
            </Link>
          );
        })}
        {busy && <p className="v2-loading">Carregando…</p>}
        {!isSearch && <div ref={sentinelRef} className="v2-bay-rail-sentinel" aria-hidden />}
      </div>
    </aside>
  );
}
