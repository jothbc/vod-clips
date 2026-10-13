import { Navigate, useSearchParams } from "react-router-dom";
import CanvasEmpty from "../components/CanvasEmpty";

export default function SearchPage() {
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q")?.trim() ?? "";

  if (!query) {
    return <Navigate to="/" replace />;
  }

  return (
    <CanvasEmpty
      title={`Busca: “${query}”`}
      hint="Os resultados aparecem na lista à esquerda. Selecione um item para abrir no canvas."
    />
  );
}
