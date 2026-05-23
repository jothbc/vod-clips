import { useState } from "react";
import type { ClipItem } from "../api/client";

interface Props {
  clips: ClipItem[];
  outputDir: string;
}

export default function ClipsGallery({ clips, outputDir }: Props) {
  const [tab, setTab] = useState<"youtube" | "reels">("youtube");

  if (!clips.length) return null;

  const filtered = clips.filter((c) =>
    tab === "youtube" ? c.youtube_url : c.reels_url
  );

  return (
    <div className="card">
      <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.1rem" }}>Generated clips</h2>
      <p className="subtitle" style={{ marginBottom: "1rem" }}>
        Output: {outputDir}
      </p>

      <div className="tabs">
        <button type="button" className={tab === "youtube" ? "active" : ""} onClick={() => setTab("youtube")}>
          YouTube (16:9)
        </button>
        <button type="button" className={tab === "reels" ? "active" : ""} onClick={() => setTab("reels")}>
          Reels (9:16)
        </button>
      </div>

      <div className="clips-grid">
        {filtered.map((clip) => {
          const url = tab === "youtube" ? clip.youtube_url : clip.reels_url;
          if (!url) return null;
          return (
            <div key={`${clip.index}-${tab}`} className={`clip-card ${tab === "reels" ? "reels" : ""}`}>
              <video src={url} controls preload="metadata" />
              <div className="clip-meta">
                <h3>{clip.title}</h3>
                <p>
                  Score {clip.score.toFixed(1)} · {formatTime(clip.start)}–{formatTime(clip.end)} · {clip.source}
                </p>
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
