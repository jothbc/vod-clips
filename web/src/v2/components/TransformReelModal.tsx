import DockTooltip from "./DockTooltip";

interface Props {
  hasWebcamRegion: boolean;
  busy?: boolean;
  onClose: () => void;
  onChoose: (includeWebcam: boolean) => void;
}

const WEBCAM_HINT =
  "Use a ação Webcam no vídeo desktop para marcar a região da câmera antes de incluir no reel.";

export default function TransformReelModal({ hasWebcamRegion, busy = false, onClose, onChoose }: Props) {
  return (
    <div className="v2-modal-backdrop" onClick={onClose}>
      <div className="v2-modal v2-transform-reel-modal" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <div>
            <h2>Transformar em reel</h2>
            <p className="v2-publish-sub">Escolha o layout vertical do mobile</p>
          </div>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose} disabled={busy}>
            Fechar
          </button>
        </div>

        <div className="v2-modal-body">
          <div className="v2-transform-reel-choices">
            <DockTooltip text={hasWebcamRegion ? "Gameplay + faixa da webcam no topo" : WEBCAM_HINT}>
              <button
                type="button"
                className="v2-transform-reel-choice v2-transform-reel-choice--cam"
                disabled={busy || !hasWebcamRegion}
                onClick={() => onChoose(true)}
              >
                <span className="v2-transform-reel-choice__icon" aria-hidden>
                  ▮
                </span>
                <strong>Com webcam</strong>
                <span className="v2-card-meta">Webcam em cima, gameplay embaixo</span>
              </button>
            </DockTooltip>

            <button
              type="button"
              className="v2-transform-reel-choice"
              disabled={busy}
              onClick={() => onChoose(false)}
            >
              <span className="v2-transform-reel-choice__icon" aria-hidden>
                ▭
              </span>
              <strong>Sem webcam</strong>
              <span className="v2-card-meta">Crop central 9:16 (atual)</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
