import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

interface BayContextValue {
  railOpen: boolean;
  opsOpen: boolean;
  toggleRail: () => void;
  toggleOps: () => void;
  closeDrawers: () => void;
  galleryOpen: boolean;
  openGallery: () => void;
  closeGallery: () => void;
  /** Registered by MediaRail so gallery/deletes can refresh the list. */
  refreshMedia: () => void;
  setRefreshMedia: (fn: (() => void) | null) => void;
  /** Registered by WatchPage to open PublishModal from OpsPanel. */
  openPublish: (() => void) | null;
  setOpenPublish: (fn: (() => void) | null) => void;
  canPublish: boolean;
  setCanPublish: (value: boolean) => void;
  /** Active watch <video> for audio-output routing. */
  hasWatchVideo: boolean;
  getWatchVideo: () => HTMLVideoElement | null;
  setWatchVideo: (el: HTMLVideoElement | null) => void;
}

const BayContext = createContext<BayContextValue | null>(null);

export function useBay(): BayContextValue {
  const ctx = useContext(BayContext);
  if (!ctx) throw new Error("useBay must be used within BayProvider");
  return ctx;
}

export function BayProvider({ children }: { children: ReactNode }) {
  const [railOpen, setRailOpen] = useState(false);
  const [opsOpen, setOpsOpen] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const refreshMediaFnRef = useRef<(() => void) | null>(null);
  const openPublishFnRef = useRef<(() => void) | null>(null);
  const watchVideoRef = useRef<HTMLVideoElement | null>(null);
  const [hasOpenPublish, setHasOpenPublish] = useState(false);
  const [hasWatchVideo, setHasWatchVideo] = useState(false);
  const [canPublish, setCanPublish] = useState(false);

  const toggleRail = useCallback(() => {
    setRailOpen((o) => !o);
    setOpsOpen(false);
  }, []);

  const toggleOps = useCallback(() => {
    setOpsOpen((o) => !o);
    setRailOpen(false);
  }, []);

  const closeDrawers = useCallback(() => {
    setRailOpen(false);
    setOpsOpen(false);
  }, []);

  const setRefreshMedia = useCallback((fn: (() => void) | null) => {
    refreshMediaFnRef.current = fn;
  }, []);

  const refreshMedia = useCallback(() => {
    refreshMediaFnRef.current?.();
  }, []);

  const invokeOpenPublish = useCallback(() => {
    openPublishFnRef.current?.();
  }, []);

  const setOpenPublish = useCallback((fn: (() => void) | null) => {
    openPublishFnRef.current = fn;
    setHasOpenPublish(fn != null);
  }, []);

  const getWatchVideo = useCallback(() => watchVideoRef.current, []);

  const setWatchVideo = useCallback((el: HTMLVideoElement | null) => {
    if (el) {
      watchVideoRef.current = el;
      setHasWatchVideo(true);
      return;
    }
    // Defer clear so remounts (Strict Mode / key change) can register the new
    // <video> before we drop hasWatchVideo and disable the audio select.
    const prev = watchVideoRef.current;
    queueMicrotask(() => {
      if (watchVideoRef.current !== prev) return;
      watchVideoRef.current = null;
      setHasWatchVideo(false);
    });
  }, []);

  const openGallery = useCallback(() => setGalleryOpen(true), []);
  const closeGallery = useCallback(() => setGalleryOpen(false), []);

  const openPublish = hasOpenPublish ? invokeOpenPublish : null;

  const value = useMemo<BayContextValue>(
    () => ({
      railOpen,
      opsOpen,
      toggleRail,
      toggleOps,
      closeDrawers,
      galleryOpen,
      openGallery,
      closeGallery,
      refreshMedia,
      setRefreshMedia,
      openPublish,
      setOpenPublish,
      canPublish,
      setCanPublish,
      hasWatchVideo,
      getWatchVideo,
      setWatchVideo,
    }),
    [
      railOpen,
      opsOpen,
      toggleRail,
      toggleOps,
      closeDrawers,
      galleryOpen,
      openGallery,
      closeGallery,
      refreshMedia,
      setRefreshMedia,
      openPublish,
      setOpenPublish,
      canPublish,
      hasWatchVideo,
      getWatchVideo,
      setWatchVideo,
    ]
  );

  return <BayContext.Provider value={value}>{children}</BayContext.Provider>;
}
