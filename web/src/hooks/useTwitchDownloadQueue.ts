import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelTwitchDownload,
  fetchTwitchDownloads,
  getTwitchDownload,
  startTwitchDownloadBatch,
  subscribeTwitchDownloadEvents,
  type TwitchDownloadState,
} from "../api/v2";
import { queryKeys } from "../queryClient";

function isActiveTwitchDownload(status: string): boolean {
  return status === "queued" || status === "downloading" || status === "running";
}

function isTerminalTwitchDownload(status: string): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

function hasActiveDownloads(downloads: TwitchDownloadState[] | undefined): boolean {
  return (downloads ?? []).some((d) => isActiveTwitchDownload(d.status));
}

export function useTwitchDownloadQueue(
  apiReady: boolean,
  opts?: { onDownloadCompleted?: (state: TwitchDownloadState) => void },
) {
  const queryClient = useQueryClient();
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const unsubsRef = useRef<Map<string, () => void>>(new Map());
  const onCompletedRef = useRef(opts?.onDownloadCompleted);
  onCompletedRef.current = opts?.onDownloadCompleted;

  const query = useQuery({
    queryKey: queryKeys.twitchDownloads,
    queryFn: fetchTwitchDownloads,
    enabled: apiReady,
    staleTime: 0,
    refetchOnMount: "always",
    // Keep polling while the gallery is open so a restart or a cleared queue
    // drops failed rows that would otherwise stay on screen.
    refetchInterval: (q) => (hasActiveDownloads(q.state.data?.downloads) ? 3_000 : 5_000),
  });

  const downloads = query.data?.downloads ?? [];

  const mergeDownload = useCallback(
    (state: TwitchDownloadState) => {
      queryClient.setQueryData<{ downloads: TwitchDownloadState[] }>(
        queryKeys.twitchDownloads,
        (prev) => {
          const list = prev?.downloads ?? [];
          const idx = list.findIndex((d) => d.id === state.id);
          if (idx >= 0) {
            const next = [...list];
            next[idx] = state;
            return { downloads: next };
          }
          return { downloads: [state, ...list] };
        },
      );
    },
    [queryClient],
  );

  const subscribeOne = useCallback(
    (downloadId: string) => {
      if (unsubsRef.current.has(downloadId)) return;
      const unsub = subscribeTwitchDownloadEvents(downloadId, (state) => {
        mergeDownload(state);
        if (state.status === "completed") {
          onCompletedRef.current?.(state);
        }
        if (isTerminalTwitchDownload(state.status)) {
          unsub();
          unsubsRef.current.delete(downloadId);
        }
      });
      unsubsRef.current.set(downloadId, unsub);
    },
    [mergeDownload],
  );

  useEffect(() => {
    for (const d of downloads) {
      if (isActiveTwitchDownload(d.status)) {
        subscribeOne(d.id);
      }
    }
  }, [downloads, subscribeOne]);

  useEffect(
    () => () => {
      for (const unsub of unsubsRef.current.values()) unsub();
      unsubsRef.current.clear();
    },
    [],
  );

  const refresh = useCallback(async () => {
    if (!apiReady) return;
    await queryClient.invalidateQueries({ queryKey: queryKeys.twitchDownloads });
  }, [apiReady, queryClient]);

  const enqueueUrls = useCallback(
    async (urls: string[]) => {
      const cleaned = urls.map((u) => u.trim()).filter(Boolean);
      if (!cleaned.length) return;
      setSubmitting(true);
      setActionError(null);
      try {
        const { downloads: started } = await startTwitchDownloadBatch(cleaned);
        for (const d of started) {
          mergeDownload(d);
          if (d.status === "completed") {
            onCompletedRef.current?.(d);
          } else if (isActiveTwitchDownload(d.status)) {
            subscribeOne(d.id);
          }
        }
        await queryClient.invalidateQueries({ queryKey: queryKeys.twitchDownloads });
      } catch (e) {
        setActionError(e instanceof Error ? e.message : String(e));
      } finally {
        setSubmitting(false);
      }
    },
    [mergeDownload, subscribeOne, queryClient],
  );

  const cancel = useCallback(
    async (downloadId: string) => {
      setActionError(null);
      try {
        await cancelTwitchDownload(downloadId);
        const state = await getTwitchDownload(downloadId);
        mergeDownload(state);
      } catch (e) {
        setActionError(e instanceof Error ? e.message : String(e));
      }
    },
    [mergeDownload],
  );

  // Query errors clear automatically on the next successful fetch (fixes sticky "Failed to fetch").
  const error = actionError ?? (query.error instanceof Error ? query.error.message : null);

  return {
    downloads,
    error,
    submitting,
    enqueueUrls,
    cancel,
    refresh,
  };
}
