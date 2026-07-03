import { useCallback, useMemo, useState } from "react";
import {
  fetchEdl,
  fetchFinal,
  renderCleanup,
  type EdlResponse,
  type FinalVideo,
  type JobState,
} from "../api/client";
import CleanupPanel from "../components/CleanupPanel";
import MediaSelectionField from "../components/MediaSelectionField";
import ProgressPanel from "../components/ProgressPanel";
import { useMediaSelection } from "../context/MediaSelectionContext";
import { useJobController } from "../hooks/useJobController";

interface Props {
  apiReady: boolean;
  health: { ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null;
}

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function CleanupView({ apiReady, health }: Props) {
  const { selectedMedia, setSelectedMedia } = useMediaSelection();
  const videoPath = selectedMedia?.path ?? "";
  const [useNvenc, setUseNvenc] = useState(true);
  const [edl, setEdl] = useState<EdlResponse | null>(null);
  const [cutSet, setCutSet] = useState<Set<number>>(new Set());
  const [rendering, setRendering] = useState(false);
  const [finals, setFinals] = useState<FinalVideo[]>([]);

  const loadEdl = useCallback(async (jobId: string) => {
    try {
      const data = await fetchEdl(jobId);
      setEdl(data);
      setCutSet(new Set(data.spans.filter((s) => s.kind === "cut").map((s) => s.index)));
    } catch {
      /* not ready */
    }
  }, []);

  const loadFinal = useCallback(async (jobId: string) => {
    try {
      const data = await fetchFinal(jobId);
      setFinals(data.videos);
    } catch {
      /* not ready */
    }
  }, []);

  const onCompleted = useCallback(
    (state: JobState) => {
      if (state.phase === "done" && rendering) {
        setRendering(false);
        loadFinal(state.id);
      } else {
        loadEdl(state.id);
      }
    },
    [loadEdl, loadFinal, rendering]
  );

  const ctrl = useJobController({ onCompleted, onFailed: () => setRendering(false) });
  const { job, error, running, start, subscribe, cancel, reset, setError } = ctrl;

  const cutSpans = useMemo(
    () => (edl ? edl.spans.filter((s) => s.kind === "cut") : []),
    [edl]
  );
  const timeSaved = useMemo(
    () =>
      edl
        ? edl.spans
            .filter((s) => cutSet.has(s.index))
            .reduce((acc, s) => acc + (s.end - s.start), 0)
        : 0,
    [edl, cutSet]
  );

  const resetUi = useCallback(() => {
    setEdl(null);
    setCutSet(new Set());
    setRendering(false);
    setFinals([]);
  }, []);

  const startJob = async () => {
    const path = videoPath.trim();
    if (!path) return;
    if (!apiReady) {
      setError("API ainda não está pronta.");
      return;
    }
    resetUi();
    await start({
      video_path: path,
      feature: "cleanup",
      preset: "cleanup",
      use_nvenc: useNvenc,
    });
  };

  const toggleCut = (index: number) => {
    setCutSet((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const runRender = async () => {
    if (!job) return;
    setError(null);
    setRendering(true);
    setFinals([]);
    try {
      await renderCleanup(job.id, {
        cut_indices: [...cutSet].sort((a, b) => a - b),
        use_nvenc: useNvenc,
      });
      subscribe(job.id);
    } catch (e) {
      setRendering(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const showReview = job?.status === "completed" && !!edl && finals.length === 0 && !rendering;

  return (
    <>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <MediaSelectionField
          returnFeature="cleanup"
          disabled={!!running || rendering || !apiReady}
          onClear={() => {
            reset();
            resetUi();
            setSelectedMedia(null);
          }}
        />
        <div className="check-row">
          <label>
            <input
              type="checkbox"
              checked={useNvenc}
              onChange={(e) => setUseNvenc(e.target.checked)}
              disabled={!!running || rendering}
            />
            NVENC (GPU) na renderização
          </label>
        </div>
        {health && (
          <p className="subtitle" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
            ffmpeg: {health.ffmpeg ? "ok" : "missing"} · ollama: {health.ollama ? "ok" : "offline"}
          </p>
        )}
        <button
          type="button"
          className="primary"
          onClick={startJob}
          disabled={!!running || rendering || !apiReady || !videoPath.trim()}
        >
          Analisar cortes
        </button>
      </div>

      <ProgressPanel job={job} onCancel={cancel} />

      {showReview && edl && (
        <div className="card">
          <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.1rem" }}>Cortes propostos</h2>
          <p className="subtitle" style={{ marginBottom: "0.75rem" }}>
            Marque o que deseja remover. Total do vídeo {fmtTime(edl.total_duration)} · removendo{" "}
            ~{fmtTime(timeSaved)} → final ~{fmtTime(edl.total_duration - timeSaved)}.
            {!edl.llm_available && " (IA indisponível — apenas silêncios)"}
          </p>

          {cutSpans.length === 0 ? (
            <p className="subtitle">Nenhum corte proposto — o vídeo já está enxuto.</p>
          ) : (
            <ul className="highlights-list" role="list">
              {cutSpans.map((s) => (
                <li key={s.index}>
                  <label className="highlight-row" style={{ cursor: "pointer" }}>
                    <span className="highlight-check">
                      <input
                        type="checkbox"
                        checked={cutSet.has(s.index)}
                        onChange={() => toggleCut(s.index)}
                      />
                    </span>
                    <span className="highlight-info">
                      <strong>
                        {s.source === "llm"
                          ? "Erro/repetição (IA)"
                          : s.source === "filler"
                            ? "Vício de linguagem"
                            : "Silêncio"}{" "}
                        · {fmtTime(s.start)} – {fmtTime(s.end)} (
                        {(s.end - s.start).toFixed(1)}s)
                      </strong>
                      {s.text && <span className="highlight-reason">“{s.text}”</span>}
                      {!s.text && s.reason && <span>{s.reason}</span>}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            className="primary"
            onClick={runRender}
            disabled={rendering || running}
          >
            {rendering ? "Renderizando…" : "Renderizar vídeo final"}
          </button>
        </div>
      )}

      {finals.length > 0 && (
        <div className="card">
          <h2 style={{ margin: "0 0 0.75rem", fontSize: "1.1rem" }}>Vídeo final</h2>
          <div className="clips-grid">
            {finals.map((v) => (
              <div key={v.format} className={`clip-card ${v.format === "reels" ? "reels" : ""}`}>
                <video controls preload="metadata" src={v.url} />
                <div className="clip-meta">
                  <h3>{v.format === "youtube" ? "YouTube (16:9)" : "Reels/TikTok (9:16)"}</h3>
                  <p>
                    <a className="link-btn" href={v.url} download={v.filename}>
                      Baixar {v.filename}
                    </a>
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {job && (job.status === "completed" || job.status === "failed") && (
        <CleanupPanel
          jobId={job.id}
          disabled={running || rendering}
          onCleared={() => {
            reset();
            resetUi();
            setSelectedMedia(null);
          }}
        />
      )}
    </>
  );
}
