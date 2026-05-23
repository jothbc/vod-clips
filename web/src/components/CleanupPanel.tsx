import { useState } from "react";
import { clearJobStorage, formatBytes, type CleanupResult } from "../api/client";

interface Props {
  jobId: string;
  disabled?: boolean;
  onCleared: () => void;
}

export default function CleanupPanel({ jobId, disabled, onCleared }: Props) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CleanupResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleClear = async () => {
    if (!confirm("Remover o VOD em temp e todos os clipes gerados deste job?")) return;
    setLoading(true);
    setError(null);
    try {
      const res = await clearJobStorage(jobId);
      setResult(res);
      onCleared();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  if (result?.already_cleaned) {
    return (
      <div className="card">
        <p className="subtitle">Arquivos temporários já foram removidos.</p>
      </div>
    );
  }

  if (result && (result.vod_deleted || result.output_deleted)) {
    return (
      <div className="card">
        <p className="subtitle">
          Limpeza concluída — {formatBytes(result.bytes_freed)} liberados.
          {result.vod_deleted && " VOD removido."}
          {result.output_deleted && " Clipes removidos."}
        </p>
      </div>
    );
  }

  return (
    <div className="card cleanup-panel">
      <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.1rem" }}>Limpar arquivos</h2>
      <p className="subtitle" style={{ marginBottom: "1rem" }}>
        Remove o vídeo em <code>temp/vods/</code> e a pasta de clipes em <code>temp/outputs/</code> deste job.
      </p>
      {error && <p className="error">{error}</p>}
      <button
        type="button"
        className="danger-button"
        onClick={handleClear}
        disabled={disabled || loading}
      >
        {loading ? "Removendo…" : "Clear — apagar temp e clipes"}
      </button>
    </div>
  );
}
