import type { ResolutionPreset } from "../api/client";

interface Props {
  sourceWidth: number;
  sourceHeight: number;
  youtubePresets: ResolutionPreset[];
  reelsPresets: ResolutionPreset[];
  youtubeResolution: ResolutionPreset;
  reelsResolution: ResolutionPreset;
  onYoutubeChange: (preset: ResolutionPreset) => void;
  onReelsChange: (preset: ResolutionPreset) => void;
  disabled?: boolean;
}

function presetKey(p: ResolutionPreset): string {
  return `${p.id}:${p.width}x${p.height}`;
}

export default function ExportResolutionPicker({
  sourceWidth,
  sourceHeight,
  youtubePresets,
  reelsPresets,
  youtubeResolution,
  reelsResolution,
  onYoutubeChange,
  onReelsChange,
  disabled = false,
}: Props) {
  const showSourceDims = sourceWidth > 0 && sourceHeight > 0;

  return (
    <div className="export-resolution">
      {showSourceDims && (
        <p className="export-resolution-source">
          Vídeo de entrada: {sourceWidth}×{sourceHeight}
        </p>
      )}
      <div className="row">
        <div>
          <label htmlFor="youtube-resolution">YouTube (16:9)</label>
          <select
            id="youtube-resolution"
            value={presetKey(youtubeResolution)}
            disabled={disabled || youtubePresets.length === 0}
            onChange={(e) => {
              const preset = youtubePresets.find((p) => presetKey(p) === e.target.value);
              if (preset) onYoutubeChange(preset);
            }}
          >
            {youtubePresets.map((p) => (
              <option key={presetKey(p)} value={presetKey(p)}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="reels-resolution">Reels (9:16)</label>
          <select
            id="reels-resolution"
            value={presetKey(reelsResolution)}
            disabled={disabled || reelsPresets.length === 0}
            onChange={(e) => {
              const preset = reelsPresets.find((p) => presetKey(p) === e.target.value);
              if (preset) onReelsChange(preset);
            }}
          >
            {reelsPresets.map((p) => (
              <option key={presetKey(p)} value={presetKey(p)}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
