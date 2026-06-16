import { useCallback, useEffect, useState } from "react";
import { waitForApi } from "./api/base";
import { fetchFeatures, fetchHealth, type FeatureInfo } from "./api/client";
import FeatureSelector from "./components/FeatureSelector";
import CaptionsView from "./features/CaptionsView";
import CleanupView from "./features/CleanupView";
import PublishView from "./features/PublishView";
import ReelsLibraryView from "./features/ReelsLibraryView";
import ReelsView from "./features/ReelsView";
import TwitchDownloadView, { PENDING_VOD_KEY } from "./features/TwitchDownloadView";

const FALLBACK_FEATURES: FeatureInfo[] = [
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
    id: "twitch_download",
    label: "Baixar da Twitch",
    description: "Baixe vários VODs em paralelo para temp/vods e use depois em Reels ou Limpar vídeo.",
    enabled: true,
  },
  {
    id: "reels_library",
    label: "Reels gerados",
    description: "Veja, reproduza e baixe todos os clipes exportados, de qualquer sessão anterior.",
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

export default function App() {
  const [apiReady, setApiReady] = useState(false);
  const [health, setHealth] = useState<{ ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null>(
    null
  );
  const [features, setFeatures] = useState<FeatureInfo[]>(FALLBACK_FEATURES);
  const [feature, setFeature] = useState("reels");
  const [pendingVodPath, setPendingVodPath] = useState<string | null>(null);

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
        if (f && f.length) setFeatures(f);
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

  const navigateWithVod = useCallback((target: "reels" | "cleanup", path: string) => {
    localStorage.setItem(PENDING_VOD_KEY, path);
    setPendingVodPath(path);
    setFeature(target);
  }, []);

  const consumePendingVod = useCallback(() => {
    const path = pendingVodPath ?? localStorage.getItem(PENDING_VOD_KEY);
    if (path) {
      localStorage.removeItem(PENDING_VOD_KEY);
      setPendingVodPath(null);
    }
    return path;
  }, [pendingVodPath]);

  return (
    <>
      <h1>Reels</h1>
      <p className="subtitle">
        Estúdio local de vídeo (100% offline) — escolha o que deseja fazer.
      </p>

      <FeatureSelector features={features} active={feature} onSelect={setFeature} />

      {feature === "reels" && (
        <ReelsView
          apiReady={apiReady}
          health={health}
          consumePendingVod={consumePendingVod}
          onOpenLibrary={() => setFeature("reels_library")}
        />
      )}
      {feature === "reels_library" && <ReelsLibraryView apiReady={apiReady} />}
      {feature === "cleanup" && (
        <CleanupView apiReady={apiReady} health={health} consumePendingVod={consumePendingVod} />
      )}
      {feature === "twitch_download" && (
        <TwitchDownloadView apiReady={apiReady} health={health} onUseVod={navigateWithVod} />
      )}
      {feature === "captions" && (
        <CaptionsView apiReady={apiReady} health={health} consumePendingVod={consumePendingVod} />
      )}
      {feature === "publish" && <PublishView apiReady={apiReady} health={health} />}
    </>
  );
}
