import type { VideoSummary } from "../../api/v2";

function formatBadgeLabel(format?: string): string | null {
  if (format === "reels") return "Mobile";
  if (format === "youtube") return "Desktop";
  return format || null;
}

/** Corner badges: VOD/CLIP, plus Desktop/Mobile for clips. */
export default function VideoCardBadges({ item }: { item: VideoSummary }) {
  const formatLabel = item.kind === "clip" ? formatBadgeLabel(item.format) : null;

  return (
    <div className="v2-card-badges">
      <span className="v2-card-badge">{item.kind === "clip" ? "CLIP" : "VOD"}</span>
      {formatLabel && <span className="v2-card-badge">{formatLabel}</span>}
    </div>
  );
}
