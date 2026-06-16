import { useCallback, useEffect, useState } from "react";
import {
  deleteReelJob,
  fetchReelsLibrary,
  type ExportedReelJob,
} from "../api/client";
import ClipsGallery from "../components/ClipsGallery";

interface Props {
  apiReady: boolean;
}

function formatDate(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export default function ReelsLibraryView({ apiReady }: Props) {
  const [jobs, setJobs] = useState<ExportedReelJob[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const loadLibrary = useCallback(async () => {
    if (!apiReady) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchReelsLibrary();
      setJobs(data.jobs);
      setExpanded((prev) => (prev && data.jobs.some((j) => j.job_id === prev) ? prev : null));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [apiReady]);

  useEffect(() => {
    loadLibrary();
  }, [loadLibrary]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") loadLibrary();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [loadLibrary]);

  const handleDelete = async (jobId: string, sourceVideo: string) => {
    const label = sourceVideo || jobId;
    if (!window.confirm(`Apagar todos os clipes desta sessão (${label})?`)) return;
    setDeleting(jobId);
    setError(null);
    try {
      await deleteReelJob(jobId);
      setJobs((prev) => prev.filter((j) => j.job_id !== jobId));
      if (expanded === jobId) setExpanded(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="card reels-library">
      <div className="reels-library-header">
        <div>
          <h2 style={{ margin: "0 0 0.25rem", fontSize: "1.1rem" }}>Reels gerados</h2>
          <p className="subtitle" style={{ margin: 0 }}>
            Todos os clipes exportados em sessões anteriores.
          </p>
        </div>
        <button type="button" onClick={loadLibrary} disabled={loading || !apiReady}>
          {loading ? "Atualizando…" : "Atualizar"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {!loading && jobs.length === 0 && (
        <p className="reels-library-empty">
          Nenhum reel exportado ainda — use <strong>Gerar Reels</strong>.
        </p>
      )}

      <ul className="reels-library-list">
        {jobs.map((job) => {
          const isOpen = expanded === job.job_id;
          return (
            <li key={job.job_id} className="reels-library-item">
              <div className="reels-library-item-header">
                <button
                  type="button"
                  className="reels-library-toggle"
                  onClick={() => setExpanded(isOpen ? null : job.job_id)}
                >
                  <span className="reels-library-toggle-title">
                    {job.source_video || "Vídeo desconhecido"}
                  </span>
                  <span className="reels-library-toggle-meta">
                    {job.clip_count} clipe{job.clip_count === 1 ? "" : "s"} · {formatDate(job.modified)}
                  </span>
                </button>
                <button
                  type="button"
                  className="danger-button"
                  disabled={deleting === job.job_id}
                  onClick={() => handleDelete(job.job_id, job.source_video)}
                >
                  {deleting === job.job_id ? "Apagando…" : "Apagar sessão"}
                </button>
              </div>
              {isOpen && (
                <div className="reels-library-expanded">
                  <ClipsGallery
                    clips={job.clips}
                    outputDir={job.output_dir}
                    showDownload
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
