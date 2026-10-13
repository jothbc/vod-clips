export type MediaKind = "vod" | "clip";

export type SelectedMedia = {
  path: string;
  kind: MediaKind;
  label: string;
};

export type GalleryPickRequest = {
  returnFeature: string;
  mode: "single" | "multi";
  filter?: "vod" | "clip" | "any";
  initialPaths?: string[];
};

export const SELECTED_MEDIA_KEY = "reels_selected_media";
export const SELECTED_PATHS_KEY = "reels_selected_media_paths";

export const FEATURE_LABELS: Record<string, string> = {
  gallery: "Galeria",
  reels: "Gerar Reels",
  cleanup: "Limpar vídeo",
  captions: "Adicionar legendas",
  publish: "Metadados para publicar",
};

export function loadSelectedMedia(): SelectedMedia | null {
  try {
    const raw = localStorage.getItem(SELECTED_MEDIA_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SelectedMedia;
    if (parsed?.path && parsed?.label) return parsed;
  } catch {
    /* ignore */
  }
  return null;
}

export function loadSelectedMediaPaths(): string[] {
  try {
    const raw = localStorage.getItem(SELECTED_PATHS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as string[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function persistSelectedMedia(media: SelectedMedia | null): void {
  if (media) {
    localStorage.setItem(SELECTED_MEDIA_KEY, JSON.stringify(media));
  } else {
    localStorage.removeItem(SELECTED_MEDIA_KEY);
  }
}

export function persistSelectedMediaPaths(paths: string[]): void {
  if (paths.length) {
    localStorage.setItem(SELECTED_PATHS_KEY, JSON.stringify(paths));
  } else {
    localStorage.removeItem(SELECTED_PATHS_KEY);
  }
}
