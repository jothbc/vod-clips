import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  loadSelectedMedia,
  loadSelectedMediaPaths,
  persistSelectedMedia,
  persistSelectedMediaPaths,
  type GalleryPickRequest,
  type SelectedMedia,
} from "../types/mediaSelection";

export interface MediaSelectionContextValue {
  selectedMedia: SelectedMedia | null;
  setSelectedMedia: (media: SelectedMedia | null) => void;
  selectedMediaPaths: string[];
  setSelectedMediaPaths: (paths: string[]) => void;
  galleryPick: GalleryPickRequest | null;
  openGalleryPick: (request: GalleryPickRequest) => void;
  cancelGalleryPick: () => void;
  completeGalleryPick: () => void;
  navigateToFeature: (featureId: string) => void;
}

const MediaSelectionContext = createContext<MediaSelectionContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
  setFeature: (id: string) => void;
}

export function MediaSelectionProvider({ children, setFeature }: ProviderProps) {
  const [selectedMedia, setSelectedMediaState] = useState<SelectedMedia | null>(loadSelectedMedia);
  const [selectedMediaPaths, setSelectedMediaPathsState] = useState<string[]>(loadSelectedMediaPaths);
  const [galleryPick, setGalleryPick] = useState<GalleryPickRequest | null>(null);

  const setSelectedMedia = useCallback((media: SelectedMedia | null) => {
    setSelectedMediaState(media);
    persistSelectedMedia(media);
  }, []);

  const setSelectedMediaPaths = useCallback((paths: string[]) => {
    setSelectedMediaPathsState(paths);
    persistSelectedMediaPaths(paths);
  }, []);

  const navigateToFeature = useCallback(
    (featureId: string) => {
      setFeature(featureId);
    },
    [setFeature]
  );

  const openGalleryPick = useCallback(
    (request: GalleryPickRequest) => {
      setGalleryPick(request);
      setFeature("gallery");
    },
    [setFeature]
  );

  const cancelGalleryPick = useCallback(() => {
    if (galleryPick) {
      setFeature(galleryPick.returnFeature);
    }
    setGalleryPick(null);
  }, [galleryPick, setFeature]);

  const completeGalleryPick = useCallback(() => {
    if (galleryPick) {
      setFeature(galleryPick.returnFeature);
    }
    setGalleryPick(null);
  }, [galleryPick, setFeature]);

  const value = useMemo(
    () => ({
      selectedMedia,
      setSelectedMedia,
      selectedMediaPaths,
      setSelectedMediaPaths,
      galleryPick,
      openGalleryPick,
      cancelGalleryPick,
      completeGalleryPick,
      navigateToFeature,
    }),
    [
      selectedMedia,
      setSelectedMedia,
      selectedMediaPaths,
      setSelectedMediaPaths,
      galleryPick,
      openGalleryPick,
      cancelGalleryPick,
      completeGalleryPick,
      navigateToFeature,
    ]
  );

  return (
    <MediaSelectionContext.Provider value={value}>{children}</MediaSelectionContext.Provider>
  );
}

export function useMediaSelection(): MediaSelectionContextValue {
  const ctx = useContext(MediaSelectionContext);
  if (!ctx) {
    throw new Error("useMediaSelection must be used within MediaSelectionProvider");
  }
  return ctx;
}
