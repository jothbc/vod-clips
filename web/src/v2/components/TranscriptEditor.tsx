import { useEffect, useState } from "react";
import { fetchTranscript, putTranscript, type TranscriptSegment } from "../../api/v2";

interface Props {
  videoId: string;
  readOnly?: boolean;
  /** When true, edits are merged into the parent VOD transcript. */
  syncToParent?: boolean;
  onSaved?: () => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1);
  return `${m}:${s.padStart(4, "0")}`;
}

export default function TranscriptEditor({
  videoId,
  readOnly = false,
  syncToParent = false,
  onSaved,
}: Props) {
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchTranscript(videoId);
        if (!cancelled) setSegments(data.segments);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Erro ao carregar");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await putTranscript(videoId, segments);
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  }

  function updateText(index: number, text: string) {
    setSegments((prev) => prev.map((s, i) => (i === index ? { ...s, text } : s)));
  }

  if (loading) return <p className="v2-loading">Carregando transcrição…</p>;

  return (
    <div className="v2-transcript">
      <h3>Transcrição</h3>
      {syncToParent && (
        <p className="v2-card-meta">Edições neste clip são salvas na transcrição do VOD.</p>
      )}
      {error && <p className="v2-error">{error}</p>}
      <div style={{ maxHeight: 360, overflowY: "auto" }}>
        {segments.map((seg, i) => (
          <div key={i} className="v2-transcript-segment">
            <span className="v2-transcript-time">
              {formatTime(seg.start)} – {formatTime(seg.end)}
            </span>
            <input
              type="text"
              value={seg.text}
              readOnly={readOnly}
              onChange={(e) => updateText(i, e.target.value)}
            />
          </div>
        ))}
      </div>
      {!readOnly && (
        <button
          type="button"
          className="v2-btn v2-btn--primary"
          style={{ marginTop: 12 }}
          disabled={saving}
          onClick={save}
        >
          {saving ? "Salvando…" : "Salvar transcrição"}
        </button>
      )}
    </div>
  );
}
