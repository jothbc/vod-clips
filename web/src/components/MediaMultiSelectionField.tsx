import { useMediaSelection } from "../context/MediaSelectionContext";
import { formatBytes } from "../api/client";

interface Props {
  returnFeature: string;
  labels: Record<string, string>;
  sizes?: Record<string, number>;
  disabled?: boolean;
}

export default function MediaMultiSelectionField({
  returnFeature,
  labels,
  sizes,
  disabled,
}: Props) {
  const { selectedMediaPaths, setSelectedMediaPaths, openGalleryPick } = useMediaSelection();

  return (
    <div className="card media-multi-selection">
      <strong>
        Vídeos selecionados ({selectedMediaPaths.length} marcado
        {selectedMediaPaths.length === 1 ? "" : "s"})
      </strong>
      {selectedMediaPaths.length === 0 ? (
        <p className="subtitle" style={{ marginTop: "0.5rem" }}>
          Nenhum vídeo selecionado. Abra a galeria para marcar um ou mais arquivos.
        </p>
      ) : (
        <ul className="stored-vods-list" role="list" style={{ marginTop: "0.75rem" }}>
          {selectedMediaPaths.map((path) => (
            <li key={path}>
              <div className="stored-vod-row">
                <span className="stored-vod-pick">
                  <strong>{labels[path] || path.split(/[/\\]/).pop() || path}</strong>
                  {sizes?.[path] !== undefined && (
                    <span> · {formatBytes(sizes[path])}</span>
                  )}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="media-selection-actions" style={{ marginTop: "0.75rem" }}>
        <button
          type="button"
          className="primary"
          disabled={disabled}
          onClick={() =>
            openGalleryPick({
              returnFeature,
              mode: "multi",
              filter: "any",
              initialPaths: selectedMediaPaths,
            })
          }
        >
          Escolher na galeria
        </button>
        {selectedMediaPaths.length > 0 && (
          <button
            type="button"
            className="link-btn"
            disabled={disabled}
            onClick={() => setSelectedMediaPaths([])}
          >
            Limpar
          </button>
        )}
      </div>
    </div>
  );
}
