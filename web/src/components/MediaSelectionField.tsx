import { useMediaSelection } from "../context/MediaSelectionContext";
import type { GalleryPickRequest } from "../types/mediaSelection";

interface Props {
  returnFeature: string;
  filter?: GalleryPickRequest["filter"];
  disabled?: boolean;
  onClear?: () => void;
}

export default function MediaSelectionField({
  returnFeature,
  filter = "any",
  disabled,
  onClear,
}: Props) {
  const { selectedMedia, setSelectedMedia, openGalleryPick } = useMediaSelection();

  const clear = () => {
    setSelectedMedia(null);
    onClear?.();
  };

  return (
    <div className="media-selection-field">
      <label className="file-picker-label">Vídeo selecionado</label>
      {selectedMedia ? (
        <div className="media-selection-current">
          <p className="file-selected">
            {selectedMedia.kind === "vod" ? "VOD" : "Clipe"}: {selectedMedia.label}
          </p>
          <p className="file-path-hint">{selectedMedia.path}</p>
        </div>
      ) : (
        <p className="subtitle" style={{ margin: "0 0 0.75rem" }}>
          Nenhum vídeo selecionado. Abra a galeria para escolher um VOD ou clipe exportado.
        </p>
      )}
      <div className="media-selection-actions">
        <button
          type="button"
          className="primary"
          disabled={disabled}
          onClick={() => openGalleryPick({ returnFeature, mode: "single", filter })}
        >
          Escolher na galeria
        </button>
        {selectedMedia && (
          <button type="button" className="link-btn" disabled={disabled} onClick={clear}>
            Limpar seleção
          </button>
        )}
      </div>
    </div>
  );
}
