import { useCallback, useEffect, useState } from "react";
import {
  fetchPickableReelClips,
  fetchReelsLibrary,
  fetchStoredVods,
  type ExportedReelJob,
  type PickableReelClip,
  type StoredVod,
} from "../api/client";

export function useMediaLibrary(apiReady: boolean) {
  const [storedVods, setStoredVods] = useState<StoredVod[]>([]);
  const [libraryJobs, setLibraryJobs] = useState<ExportedReelJob[]>([]);
  const [pickableClips, setPickableClips] = useState<PickableReelClip[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!apiReady) return;
    setLoading(true);
    setError(null);
    try {
      const [vodsRes, libraryRes, pickableRes] = await Promise.all([
        fetchStoredVods(),
        fetchReelsLibrary(),
        fetchPickableReelClips(),
      ]);
      setStoredVods(vodsRes.vods);
      setLibraryJobs(libraryRes.jobs);
      setPickableClips(pickableRes.clips);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [apiReady]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refresh]);

  const resolveLabel = useCallback(
    (path: string): string => {
      const vod = storedVods.find((v) => v.path === path);
      if (vod) return vod.filename;
      const clip = pickableClips.find((c) => c.path === path);
      if (clip) return clip.title;
      return path.split(/[/\\]/).pop() || path;
    },
    [storedVods, pickableClips]
  );

  const resolveKind = useCallback(
    (path: string): "vod" | "clip" => {
      if (storedVods.some((v) => v.path === path)) return "vod";
      return "clip";
    },
    [storedVods]
  );

  return {
    storedVods,
    libraryJobs,
    pickableClips,
    loading,
    error,
    refresh,
    resolveLabel,
    resolveKind,
    setLibraryJobs,
  };
}
