interface Props {
  title?: string;
  hint?: string;
}

export default function CanvasEmpty({
  title = "Nenhuma mídia selecionada",
  hint = "Escolha um VOD ou clipe na lista à esquerda para abrir no canvas.",
}: Props) {
  return (
    <div className="v2-canvas-empty">
      <p className="v2-canvas-empty-title">{title}</p>
      <p className="v2-canvas-empty-hint">{hint}</p>
    </div>
  );
}
