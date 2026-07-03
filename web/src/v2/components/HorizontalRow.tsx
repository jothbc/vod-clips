import { Link } from "react-router-dom";
import type { VideoSummary } from "../../api/v2";

interface Props {
  title: string;
  items: VideoSummary[];
  vertical?: boolean;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function HorizontalRow({ title, items, vertical }: Props) {
  if (!items.length) return null;

  return (
    <section className="v2-section">
      <div className="v2-section-header">
        <h2 className="v2-section-title">{title}</h2>
      </div>
      <div className="v2-row">
        {items.map((item) => (
          <Link
            key={item.id}
            to={`/watch/${item.id}`}
            className={`v2-card${vertical ? " v2-card--vertical" : ""}`}
          >
            <div className="v2-card-thumb">
              <video src={item.stream_url} muted preload="metadata" />
              {item.kind === "clip" && (
                <span className="v2-card-badge">
                  {item.format === "reels" ? "Mobile" : item.format === "youtube" ? "Desktop" : item.format || "clip"}
                </span>
              )}
            </div>
            <div className="v2-card-body">
              <p className="v2-card-title">{item.title}</p>
              <p className="v2-card-meta">
                {item.duration > 0 ? formatDuration(item.duration) : "—"}
                {item.clip_count ? ` · ${item.clip_count} clipes` : ""}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
