import { useEffect, useState } from "react";
import { waitForApi } from "../api/base";
import { fetchFeatures, fetchHealth, type FeatureInfo } from "../api/client";
import FeatureSelector from "../components/FeatureSelector";
import { MediaSelectionProvider } from "../context/MediaSelectionContext";
import CaptionsView from "../features/CaptionsView";
import CleanupView from "../features/CleanupView";
import GalleryView from "../features/GalleryView";
import PublishView from "../features/PublishView";
import ReelsView from "../features/ReelsView";

const GALLERY_FEATURE: FeatureInfo = {
  id: "gallery",
  label: "Galeria",
  description:
    "Upload, downloads da Twitch, VODs e clipes exportados — selecione vídeos para usar nas outras abas.",
  enabled: true,
};

const FALLBACK_FEATURES: FeatureInfo[] = [
  GALLERY_FEATURE,
  {
    id: "reels",
    label: "Gerar Reels",
    description: "Analisa o vídeo e lista os highlights para você escolher antes de gerar os clipes.",
    enabled: true,
  },
  {
    id: "cleanup",
    label: "Limpar vídeo",
    description:
      "Corta silêncios entre as falas e erros detectados por IA, gerando um único vídeo corrigido.",
    enabled: true,
  },
  {
    id: "captions",
    label: "Adicionar legendas",
    description: "Legendas estilo Reels/TikTok com texto editável antes de gerar.",
    enabled: true,
  },
  {
    id: "publish",
    label: "Metadados para publicar",
    description: "Gera título, descrição, tags e thumbnail para YouTube ou Short-form.",
    enabled: true,
  },
];

const REMOVED_FEATURE_IDS = new Set(["twitch_download", "reels_library"]);

function normalizeFeatures(raw: FeatureInfo[]): FeatureInfo[] {
  const filtered = raw.filter((f) => !REMOVED_FEATURE_IDS.has(f.id));
  const hasGallery = filtered.some((f) => f.id === "gallery");
  const merged = hasGallery ? filtered : [GALLERY_FEATURE, ...filtered];
  return [
    ...merged.filter((f) => f.id === "gallery"),
    ...merged.filter((f) => f.id !== "gallery"),
  ];
}

function AppContent() {
  const [apiReady, setApiReady] = useState(false);
  const [health, setHealth] = useState<{ ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null>(
    null
  );
  const [features, setFeatures] = useState<FeatureInfo[]>(FALLBACK_FEATURES);
  const [feature, setFeature] = useState("gallery");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await waitForApi();
        if (cancelled) return;
        setApiReady(true);
        const [h, f] = await Promise.all([
          fetchHealth().catch(() => null),
          fetchFeatures().catch(() => FALLBACK_FEATURES),
        ]);
        if (cancelled) return;
        setHealth(h);
        if (f && f.length) setFeatures(normalizeFeatures(f));
      } catch {
        if (!cancelled) {
          setApiReady(false);
          setHealth(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <MediaSelectionProvider setFeature={setFeature}>
      <h1>Reels</h1>
      <p className="subtitle">
        Estúdio local de vídeo (100% offline) — escolha o que deseja fazer.
      </p>

      <FeatureSelector features={features} active={feature} onSelect={setFeature} />

      {feature === "gallery" && <GalleryView apiReady={apiReady} health={health} />}
      {feature === "reels" && (
        <ReelsView apiReady={apiReady} health={health} onOpenGallery={() => setFeature("gallery")} />
      )}
      {feature === "cleanup" && <CleanupView apiReady={apiReady} health={health} />}
      {feature === "captions" && <CaptionsView apiReady={apiReady} health={health} />}
      {feature === "publish" && <PublishView apiReady={apiReady} health={health} />}
    </MediaSelectionProvider>
  );
}

export default function LegacyApp() {
  return (
    <div className="legacy-root">
      <AppContent />
    </div>
  );
}
