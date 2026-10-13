import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 2_000,
    },
  },
});

export const queryKeys = {
  twitchDownloads: ["twitch", "downloads"] as const,
  gallery: ["gallery"] as const,
  systemStatus: ["system", "status"] as const,
  jobs: (limit = 50) => ["jobs", { limit }] as const,
  videos: (offset: number, limit: number) => ["videos", { offset, limit }] as const,
};
