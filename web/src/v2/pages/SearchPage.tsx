import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { waitForApi } from "../../api/base";
import { searchVideos, type VideoSummary } from "../../api/v2";
import AppHeader from "../components/AppHeader";
import HorizontalRow from "../components/HorizontalRow";
import "../v2.css";

export default function SearchPage() {
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q")?.trim() ?? "";
  const [results, setResults] = useState<VideoSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!query) {
      setResults([]);
      setError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        await waitForApi();
        const data = await searchVideos(query);
        if (!cancelled) setResults(data.videos);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Erro na busca");
          setResults([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [query]);

  if (!query) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="v2-root">
      <div className="v2-shell">
        <AppHeader />
        <section className="v2-section">
          <div className="v2-section-header">
            <h2 className="v2-section-title">Resultados para &ldquo;{query}&rdquo;</h2>
          </div>
          {loading && <p className="v2-loading">Buscando…</p>}
          {error && <p className="v2-error">{error}</p>}
          {!loading && !error && results.length === 0 && (
            <p className="v2-empty">Nenhum vídeo ou clipe encontrado.</p>
          )}
        </section>
        {!loading && results.length > 0 && (
          <HorizontalRow title={`${results.length} resultado${results.length !== 1 ? "s" : ""}`} items={results} />
        )}
      </div>
    </div>
  );
}
