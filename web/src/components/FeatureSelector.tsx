import type { FeatureInfo } from "../api/client";

interface Props {
  features: FeatureInfo[];
  active: string;
  onSelect: (id: string) => void;
  disabled?: boolean;
}

export default function FeatureSelector({ features, active, onSelect, disabled }: Props) {
  return (
    <div className="feature-selector">
      {features.map((f) => {
        const isActive = f.id === active;
        const locked = !f.enabled || disabled;
        return (
          <button
            key={f.id}
            type="button"
            className={`feature-card ${isActive ? "active" : ""} ${
              !f.enabled ? "locked" : ""
            }`}
            disabled={locked}
            onClick={() => f.enabled && !disabled && onSelect(f.id)}
          >
            <strong>{f.label}</strong>
            <span>{f.description}</span>
            {!f.enabled && <em className="feature-soon">Em breve</em>}
          </button>
        );
      })}
    </div>
  );
}
