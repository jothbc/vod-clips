interface Props {
  onDefineWebcam: () => void;
  onContinueWithout: () => void;
  onClose: () => void;
}

export default function WebcamPromptModal({ onDefineWebcam, onContinueWithout, onClose }: Props) {
  return (
    <div className="v2-modal-backdrop" onClick={onClose}>
      <div className="v2-modal v2-webcam-prompt-modal" onClick={(e) => e.stopPropagation()}>
        <div className="v2-modal-header">
          <div>
            <h2>Webcam antes dos highlights?</h2>
            <p className="v2-publish-sub">A análise pode demorar bastante — vale definir a câmera agora</p>
          </div>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        <div className="v2-modal-body">
          <p className="v2-webcam-prompt-lead">
            Sem a região da webcam, você não consegue gerar o mobile com a câmera no topo depois
            que a análise terminar. Defina agora ou continue só com desktop / mobile sem webcam.
          </p>

          <div className="v2-transform-reel-choices">
            <button
              type="button"
              className="v2-transform-reel-choice v2-transform-reel-choice--cam"
              onClick={onDefineWebcam}
            >
              <span className="v2-transform-reel-choice__icon" aria-hidden>
                ▮
              </span>
              <strong>Definir webcam agora</strong>
              <span className="v2-card-meta">Marca a região da câmera e depois abre o gerador</span>
            </button>

            <button type="button" className="v2-transform-reel-choice" onClick={onContinueWithout}>
              <span className="v2-transform-reel-choice__icon" aria-hidden>
                ▭
              </span>
              <strong>Continuar sem webcam</strong>
              <span className="v2-card-meta">Abre o gerador; mobile com webcam fica indisponível</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
