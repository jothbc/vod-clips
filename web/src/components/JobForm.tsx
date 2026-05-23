import type { AnalysisMode } from "../api/client";
import FilePicker from "./FilePicker";

export interface JobFormValues {
  videoPath: string;
  mode: AnalysisMode;
  preset: string;
  maxClips: number;
  useNvenc: boolean;
  cleanup: boolean;
  resume: boolean;
}

interface Props {
  values: JobFormValues;
  onChange: (v: JobFormValues) => void;
  onSubmit: () => void;
  disabled: boolean;
  health: { ffmpeg: boolean; ollama: boolean } | null;
}

export default function JobForm({ values, onChange, onSubmit, disabled, health }: Props) {
  return (
    <div className="card">
      <FilePicker
        value={values.videoPath}
        onChange={(videoPath) => onChange({ ...values, videoPath })}
        disabled={disabled}
      />

      <div className="row" style={{ marginTop: "1rem" }}>
        <div>
          <label htmlFor="mode">Analysis mode</label>
          <select
            id="mode"
            value={values.mode}
            onChange={(e) => onChange({ ...values, mode: e.target.value as AnalysisMode })}
            disabled={disabled}
          >
            <option value="auto">auto (heuristic + VLM)</option>
            <option value="gaming">gaming (heuristic only)</option>
            <option value="multimodal">multimodal (VLM)</option>
          </select>
        </div>
        <div>
          <label htmlFor="max-clips">Max clips</label>
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
            checked={values.cleanup}
            onChange={(e) => onChange({ ...values, cleanup: e.target.checked })}
            disabled={disabled}
          />
          Cleanup proxy after run
        </label>
        <label>
          <input
            type="checkbox"
            checked={values.resume}
            onChange={(e) => onChange({ ...values, resume: e.target.checked })}
            disabled={disabled}
          />
          Resume checkpoint
        </label>
      </div>

      {health && (
        <p className="subtitle" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
          ffmpeg: {health.ffmpeg ? "ok" : "missing"} · ollama: {health.ollama ? "ok" : "offline"}
        </p>
      )}

      <button type="button" className="primary" onClick={onSubmit} disabled={disabled || !values.videoPath.trim()}>
        Start processing
      </button>
    </div>
  );
}
