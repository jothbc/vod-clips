import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelTwitchDownload,
  fetchTwitchDownloads,
  getTwitchDownload,
  startTwitchDownloadBatch,
  subscribeTwitchDownloadEvents,
  type TwitchDownloadState,
} from "../api/client";

/** Track parallel Twitch downloads with SSE + polling fallback. */
export function useTwitchDownloadQueue(apiReady: boolean) {
  const [downloads, setDownloads] = useState<TwitchDownloadState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const unsubsRef = useRef<Map<string, () => void>>(new Map());

  const mergeDownload = useCallback((state: TwitchDownloadState) => {
    setDownloads((prev) => {
      const idx = prev.findIndex((d) => d.id === state.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = state;
        return next;
      }
      return [state, ...prev];
    });
  }, []);

  const subscribeOne = useCallback(
    (downloadId: string) => {
      if (unsubsRef.current.has(downloadId)) return;
      const unsub = subscribeTwitchDownloadEvents(
        downloadId,
        (state) => {
          mergeDownload(state);
          if (["completed", "failed", "cancelled"].includes(state.status)) {
            unsub();
            unsubsRef.current.delete(downloadId);
          }
        },
        () => {
          getTwitchDownload(downloadId).then(mergeDownload).catch(() => {});
        }
      );
      unsubsRef.current.set(downloadId, unsub);
    },
    [mergeDownload]
  );

  const refresh = useCallback(async () => {
    if (!apiReady) return;
    try {
      const data = await fetchTwitchDownloads();
      setDownloads(data.downloads);
      for (const d of data.downloads) {
        if (d.status === "queued" || d.status === "running") {
          subscribeOne(d.id);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [apiReady, subscribeOne]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(
    () => () => {
      for (const unsub of unsubsRef.current.values()) unsub();
      unsubsRef.current.clear();
    },
    []
  );

  const enqueueUrls = useCallback(
    async (urls: string[]) => {
      const cleaned = urls.map((u) => u.trim()).filter(Boolean);
      if (!cleaned.length) return;
      setSubmitting(true);
      setError(null);
      try {
        const { downloads: started } = await startTwitchDownloadBatch(cleaned);
        for (const d of started) {
          mergeDownload(d);
          if (d.status === "queued" || d.status === "running") {
            subscribeOne(d.id);
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setSubmitting(false);
      }
    },
    [mergeDownload, subscribeOne]
  );

  const cancel = useCallback(
    async (downloadId: string) => {
      setError(null);
      try {
        await cancelTwitchDownload(downloadId);
        const state = await getTwitchDownload(downloadId);
        mergeDownload(state);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [mergeDownload]
  );

  return {
    downloads,
    error,
    submitting,
    enqueueUrls,
    cancel,
    refresh,
  };
}
