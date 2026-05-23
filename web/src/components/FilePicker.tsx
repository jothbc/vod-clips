import { useRef, useState } from "react";
import { uploadVodWithProgress } from "../api/client";

interface Props {
  value: string;
  onChange: (path: string) => void;
  disabled?: boolean;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

export default function FilePicker({ value, onChange, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [sizeLabel, setSizeLabel] = useState("");

  const onFileInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setDisplayName(file.name);
    setSizeLabel(formatSize(file.size));
    setUploading(true);
    setUploadPercent(0);

    try {
      const res = await uploadVodWithProgress(file, setUploadPercent);
      onChange(res.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      onChange("");
      setDisplayName("");
      setSizeLabel("");
    } finally {
      setUploading(false);
      setUploadPercent(0);
      e.target.value = "";
    }
  };

  return (
    <div className="file-picker">
      <label className="file-picker-label">VOD (.mp4) — upload para temp do servidor</label>
      <p className="subtitle" style={{ margin: "0 0 0.75rem" }}>
        O vídeo é copiado para <code>temp/vods/</code> no projeto (funciona no WSL sem acessar o disco do Windows).
      </p>

      <div className="file-picker-row">
        <label className={`file-input-button ${disabled || uploading ? "disabled" : ""}`}>
          <input
            ref={inputRef}
            type="file"
            accept="video/mp4,.mp4"
            disabled={disabled || uploading}
            onChange={onFileInput}
          />
          {uploading ? `Enviando ${uploadPercent.toFixed(0)}%…` : "Escolher vídeo"}
        </label>
      </div>

      {uploading && (
        <div className="progress-bar" style={{ marginTop: "0.75rem" }}>
          <div className="progress-fill" style={{ width: `${uploadPercent}%` }} />
        </div>
      )}

      {displayName && !uploading && (
        <p className="file-selected">
          Pronto: {displayName} ({sizeLabel})
        </p>
      )}

      {value && !uploading && (
        <p className="file-path-hint" style={{ marginTop: "0.35rem" }}>
          Salvo em: {value}
        </p>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  );
}
