import { useCallback, useEffect, useState } from "react";
import { fetchVideos, type VideoSummary } from "../../api/v2";

export function useVideoFeed(pageSize = 24) {
  const [items, setItems] = useState<VideoSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (reset = false) => {
      const nextOffset = reset ? 0 : offset;
      if (!reset && items.length >= total && total > 0) return;
      setLoading(true);
      setError(null);
      try {
        const data = await fetchVideos(nextOffset, pageSize);
        setTotal(data.total);
        setItems((prev) => (reset ? data.videos : [...prev, ...data.videos]));
        setOffset(nextOffset + data.videos.length);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load feed");
      } finally {
        setLoading(false);
      }
    },
    [offset, items.length, pageSize, total]
  );

  useEffect(() => {
    load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadMore = useCallback(() => {
    if (!loading && items.length < total) load(false);
  }, [load, loading, items.length, total]);

  const hasMore = items.length < total;

  return { items, loading, error, hasMore, loadMore, refresh: () => load(true) };
}
