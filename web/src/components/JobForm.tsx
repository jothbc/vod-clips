import type { AnalysisMode } from "../api/client";
import MediaSelectionField from "./MediaSelectionField";

export interface JobFormValues {
  videoPath: string;
  mode: AnalysisMode;
  preset: string;
  maxClips: number;
  useNvenc: boolean;
  cleanup: boolean;
  resume: boolean;
  exportAllClips: boolean;
}

interface Props {
  values: JobFormValues;
  onChange: (v: JobFormValues) => void;
  onSubmit: () => void;
  onNewVideo?: () => void;
  disabled: boolean;
  apiReady?: boolean;
  health: { ffmpeg: boolean; ollama: boolean; yt_dlp?: boolean } | null;
}

export default function JobForm({
  values,
  onChange,
  onSubmit,
  onNewVideo,
  disabled,
  apiReady = true,
  health,
}: Props) {
  return (
    <div className="card">
      <MediaSelectionField returnFeature="reels" disabled={disabled} onClear={onNewVideo} />

      <div className="row" style={{ marginTop: "1rem" }}>
        <div>
          <label htmlFor="max-clips">Max highlights</label>
          <input
            id="max-clips"
            type="number"
            min={1}
            max={50}
            value={values.maxClips}
            onChange={(e) => onChange({ ...values, maxClips: Number(e.target.value) })}
            disabled={disabled}
          />
        </div>
      </div>

      <div className="check-row">
        <label>
          <input
            type="checkbox"
            checked={values.useNvenc}
            onChange={(e) => onChange({ ...values, useNvenc: e.target.checked })}
            disabled={disabled}
          />
          NVENC export
        </label>
        <label>
          <input
            type="checkbox"
            checked={values.exportAllClips}
            onChange={(e) => onChange({ ...values, exportAllClips: e.target.checked })}
            disabled={disabled}
          />
          Export all clips immediately (skip review)
        </label>
      </div>

      {health && (
        <p className="subtitle" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
          ffmpeg: {health.ffmpeg ? "ok" : "missing"} · ollama: {health.ollama ? "ok" : "offline"}
          {health.yt_dlp !== undefined && (
            <> · yt-dlp: {health.yt_dlp ? "ok" : "missing"}</>
          )}
        </p>
      )}

      <button
        type="button"
        className="primary"
        onClick={onSubmit}
        disabled={disabled || !values.videoPath.trim() || !apiReady}
      >
        {values.exportAllClips ? "Analyze and export all" : "Analyze video"}
      </button>
    </div>
  );
}
