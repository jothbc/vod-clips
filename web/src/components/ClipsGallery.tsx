import { useState } from "react";
import { apiUrl } from "../api/base";
import type { ClipItem } from "../api/client";

interface Props {
  clips: ClipItem[];
  outputDir: string;
  showDownload?: boolean;
}

export default function ClipsGallery({ clips, outputDir, showDownload = false }: Props) {
  const [tab, setTab] = useState<"youtube" | "reels">("youtube");
  const [activePlayIndex, setActivePlayIndex] = useState<number | null>(null);

  if (!clips.length) return null;

  const exported = clips.filter((c) => c.youtube_url || c.reels_url);
  const filtered = exported.filter((c) => (tab === "youtube" ? c.youtube_url : c.reels_url));

  return (
    <div className="card">
      <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.1rem" }}>Generated clips</h2>
      <p className="subtitle" style={{ marginBottom: "1rem" }}>
        Output: {outputDir}
      </p>

      <div className="tabs">
        <button
          type="button"
          className={tab === "youtube" ? "active" : ""}
          onClick={() => {
            setTab("youtube");
            setActivePlayIndex(null);
          }}
        >
          YouTube (16:9)
        </button>
        <button
          type="button"
          className={tab === "reels" ? "active" : ""}
          onClick={() => {
            setTab("reels");
            setActivePlayIndex(null);
          }}
        >
          Reels (9:16)
        </button>
      </div>

      <div className="clips-grid">
        {filtered.map((clip) => {
          const rel = tab === "youtube" ? clip.youtube_url : clip.reels_url;
          if (!rel) return null;
          const src = apiUrl(rel);
          const filename =
            tab === "youtube" ? clip.youtube_filename : clip.reels_filename;
          const isActive = activePlayIndex === clip.index;

          return (
            <div key={`${clip.index}-${tab}`} className={`clip-card ${tab === "reels" ? "reels" : ""}`}>
              {isActive ? (
                <video src={src} controls preload="metadata" playsInline />
              ) : (
                <button
                  type="button"
                  className="clip-preview-placeholder"
                  onClick={() => setActivePlayIndex(clip.index)}
                >
                  <span>▶ Play clip</span>
                  <span className="file-path-hint">{clip.title}</span>
                </button>
              )}
              <div className="clip-meta">
                <h3>{clip.title}</h3>
                <p>
                  Score {clip.score.toFixed(1)} · {formatTime(clip.start)}–{formatTime(clip.end)} ·{" "}
                  {clip.source}
                </p>
                {showDownload && (
                  <a className="clip-download" href={src} download={filename || undefined}>
                    Baixar MP4
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
