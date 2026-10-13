import { useCallback, useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { waitForApi } from "../../api/base";
import CommandStrip from "../components/CommandStrip";
import GalleryModal from "../components/GalleryModal";
import MediaRail from "../components/MediaRail";
import { BayProvider, useBay } from "../context/BayContext";
import OpsPanel from "./OpsPanel";
import "../v2.css";

function BayChrome() {
  const { railOpen, opsOpen, closeDrawers, galleryOpen, closeGallery, refreshMedia } = useBay();
  const [apiReady, setApiReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await waitForApi();
        if (!cancelled) setApiReady(true);
      } catch {
        if (!cancelled) setApiReady(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onGalleryChanged = useCallback(() => {
    refreshMedia();
  }, [refreshMedia]);

  return (
    <div className="v2-root v2-root--bay">
      <CommandStrip />
      {(railOpen || opsOpen) && (
        <button
          type="button"
          className="v2-bay-backdrop"
          aria-label="Fechar painel"
          onClick={closeDrawers}
        />
      )}
      <div className="v2-bay">
        <MediaRail />
        <main className="v2-bay-canvas">
          <Outlet />
        </main>
        <OpsPanel />
      </div>
      {galleryOpen && (
        <GalleryModal apiReady={apiReady} onClose={closeGallery} onChanged={onGalleryChanged} />
      )}
    </div>
  );
}

export default function BayLayout() {
  return (
    <BayProvider>
      <BayChrome />
    </BayProvider>
  );
}
