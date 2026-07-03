import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { ClipSummary } from "../../api/v2";

interface Props {
  clips: ClipSummary[];
}

export default function ClipCarousel({ clips }: Props) {
  const [index, setIndex] = useState(0);
  const items = clips.slice(0, 3);

  useEffect(() => {
    if (items.length <= 1) return;
    const timer = setInterval(() => {
      setIndex((i) => (i + 1) % items.length);
    }, 6000);
    return () => clearInterval(timer);
  }, [items.length]);

  if (!items.length) {
    return (
      <div className="v2-hero v2-empty">
        <p>Nenhum clipe recente — importe um VOD na galeria.</p>
      </div>
    );
  }

  return (
    <div className="v2-hero">
      {items.map((clip, i) => (
        <Link
          key={clip.id}
          to={`/watch/${clip.parent_id || clip.id}`}
          className={`v2-hero-slide${i === index ? " active" : ""}`}
        >
          {clip.thumbnail_url ? (
            <img src={clip.thumbnail_url} alt="" />
          ) : (
            <video src={clip.stream_url} muted preload="metadata" />
          )}
          <div className="v2-hero-overlay">
            <h2 className="v2-hero-title">{clip.title}</h2>
            <p className="v2-hero-meta">
              {clip.format === "reels" ? "Mobile" : "Desktop"} · {clip.duration_label}
            </p>
          </div>
        </Link>
      ))}
      {items.length > 1 && (
        <div className="v2-hero-dots">
          {items.map((_, i) => (
            <button
              key={i}
              type="button"
              className={`v2-hero-dot${i === index ? " active" : ""}`}
              onClick={(e) => {
                e.preventDefault();
                setIndex(i);
              }}
              aria-label={`Slide ${i + 1}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
