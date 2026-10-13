export type ClipFormat = "youtube" | "reels";

interface Props {
  formats: string[];
  active: ClipFormat;
  onChange: (format: ClipFormat) => void;
}

export default function FormatToggle({ formats, active, onChange }: Props) {
  const hasDesktop = formats.includes("youtube");
  const hasMobile = formats.includes("reels");
  if (!hasDesktop && !hasMobile) return null;
  if (hasDesktop && !hasMobile) return null;
  if (!hasDesktop && hasMobile) return null;

  return (
    <div className="v2-format-toggle" role="group" aria-label="Formato do clipe">
      <button
        type="button"
        className={`v2-format-toggle__btn${active === "youtube" ? " v2-format-toggle__btn--active" : ""}`}
        disabled={!hasDesktop}
        title="Desktop (16:9)"
        onClick={() => onChange("youtube")}
      >
        🖥
      </button>
      <button
        type="button"
        className={`v2-format-toggle__btn${active === "reels" ? " v2-format-toggle__btn--active" : ""}`}
        disabled={!hasMobile}
        title="Mobile (9:16)"
        onClick={() => onChange("reels")}
      >
        📱
      </button>
    </div>
  );
}
