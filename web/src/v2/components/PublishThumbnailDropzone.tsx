import { useCallback, useRef, useState } from "react";

interface Props {
  sessionId: string;
  thumbSrc: string;
  uploading: boolean;
  onPick: (file: File) => void | Promise<void>;
}

export default function PublishThumbnailDropzone({
  sessionId,
  thumbSrc,
  uploading,
  onPick,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const acceptImage = useCallback((file: File | undefined) => {
    if (!file || !sessionId) return;
    if (!file.type.startsWith("image/")) return;
    void onPick(file);
  }, [onPick, sessionId]);

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    acceptImage(e.dataTransfer.files?.[0]);
  }

  return (
    <div className="v2-publish-thumb-dropzone-wrap">
      <div
        className={`v2-publish-thumb-dropzone${dragOver ? " v2-publish-thumb-dropzone--active" : ""}${
          thumbSrc ? " v2-publish-thumb-dropzone--filled" : ""
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        role="button"
        tabIndex={0}
        aria-label="Selecionar ou arrastar imagem de capa"
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/*"
          className="v2-publish-thumb-dropzone__input"
          disabled={!sessionId || uploading}
          onChange={(e) => {
            acceptImage(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {thumbSrc ? (
          <>
            <img src={thumbSrc} alt="Thumbnail" className="v2-publish-thumb-dropzone__preview" />
            <div className="v2-publish-thumb-dropzone__overlay">
              <span>{uploading ? "Enviando…" : "Trocar capa"}</span>
              <p>Clique ou arraste outra imagem</p>
            </div>
          </>
        ) : (
          <div className="v2-publish-thumb-dropzone__empty">
            <span className="v2-publish-thumb-dropzone__icon" aria-hidden>
              ↑
            </span>
            <strong>Capa do vídeo</strong>
            <p>{uploading ? "Enviando…" : "Arraste uma imagem ou clique para escolher"}</p>
            <p className="v2-card-meta">JPG, PNG ou WebP — até 8 MB</p>
          </div>
        )}
      </div>
      {thumbSrc && (
        <a href={thumbSrc} download className="v2-btn v2-btn--sm v2-publish-thumb-dropzone__download">
          Baixar capa
        </a>
      )}
    </div>
  );
}
