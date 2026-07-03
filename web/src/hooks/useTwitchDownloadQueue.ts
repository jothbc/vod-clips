import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelTwitchDownload,
  fetchTwitchDownloads,
  getTwitchDownload,
  startTwitchDownloadBatch,
  subscribeTwitchDownloadEvents,
  type TwitchDownloadState,
} from "../api/client";

function isActiveTwitchDownload(status: string): boolean {
  return status === "queued" || status === "downloading" || status === "running";
}

function isTerminalTwitchDownload(status: string): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

export function useTwitchDownloadQueue(
  apiReady: boolean,
  opts?: { onDownloadCompleted?: (state: TwitchDownloadState) => void },
) {
  const [downloads, setDownloads] = useState<TwitchDownloadState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const unsubsRef = useRef<Map<string, () => void>>(new Map());

  const onDownloadCompleted = opts?.onDownloadCompleted;

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
          if (state.status === "completed") {
            onDownloadCompleted?.(state);
          }
          if (isTerminalTwitchDownload(state.status)) {
            unsub();
            unsubsRef.current.delete(downloadId);
          }
        },
        () => {
          getTwitchDownload(downloadId).then((state) => {
            mergeDownload(state);
            if (state.status === "completed") {
              onDownloadCompleted?.(state);
            }
          }).catch(() => {});
        }
      );
      unsubsRef.current.set(downloadId, unsub);
    },
    [mergeDownload, onDownloadCompleted],
  );

  const refresh = useCallback(async () => {
    if (!apiReady) return;
    try {
      const data = await fetchTwitchDownloads();
      setDownloads(data.downloads);
      for (const d of data.downloads) {
        if (isActiveTwitchDownload(d.status)) {
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
          if (d.status === "completed") {
            onDownloadCompleted?.(d);
          } else if (isActiveTwitchDownload(d.status)) {
            subscribeOne(d.id);
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setSubmitting(false);
      }
    },
    [mergeDownload, subscribeOne, onDownloadCompleted]
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
