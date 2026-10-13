import { useCallback, useEffect, useState } from "react";
import { fetchVideo, type VideoDetail } from "../../api/v2";

export function useVideo(id: string | undefined) {
  const [video, setVideo] = useState<VideoDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchVideo(id);
      setVideo(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load video");
      setVideo(null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { video, loading, error, refresh };
}
