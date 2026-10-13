interface ConfirmModalProps {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  title,
  message,
  confirmLabel = "Confirmar",
  cancelLabel = "Cancelar",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  return (
    <div className="v2-modal-backdrop v2-confirm-backdrop" onClick={onCancel} role="presentation">
      <div
        className="v2-modal v2-confirm-modal"
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="v2-confirm-title"
        aria-describedby="v2-confirm-message"
      >
        <div className="v2-modal-header">
          <h2 id="v2-confirm-title">{title}</h2>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onCancel}>
            Fechar
          </button>
        </div>
        <div className="v2-modal-body">
          <p id="v2-confirm-message" className="v2-confirm-message">
            {message}
          </p>
          <div className="v2-modal-actions">
            <button type="button" className="v2-btn v2-btn--ghost" onClick={onCancel}>
              {cancelLabel}
            </button>
            <button
              type="button"
              className={`v2-btn ${danger ? "v2-btn--danger" : "v2-btn--primary"}`}
              onClick={onConfirm}
              autoFocus
            >
              {confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
