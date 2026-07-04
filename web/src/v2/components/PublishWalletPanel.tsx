import { useCallback, useEffect, useState } from "react";
import {
  createPublishTarget,
  deletePublishTarget,
  disconnectPublishTarget,
  fetchPublishTargets,
  startPublishTargetAuth,
  updatePublishTarget,
  type PublishTarget,
} from "../../api/v2";
import PublishTargetCard from "./PublishTargetCard";
import PublishTargetForm from "./PublishTargetForm";

interface Props {
  selectedTargetId?: string;
  onSelectTarget?: (id: string) => void;
  compact?: boolean;
}

export default function PublishWalletPanel({
  selectedTargetId,
  onSelectTarget,
  compact = false,
}: Props) {
  const [targets, setTargets] = useState<PublishTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<PublishTarget | null | "new">(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchPublishTargets();
      setTargets(res.targets);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar carteira");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (ev.data === "publish-oauth-done") void reload();
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [reload]);

  async function handleConnect(id: string) {
    try {
      const { auth_url } = await startPublishTargetAuth(id);
      window.open(auth_url, "_blank", "width=520,height=720");
    } catch (e) {
      setError(e instanceof Error ? e.message : "OAuth indisponível");
    }
  }

  if (editing) {
    return (
      <div className="v2-wallet-panel">
        <h3 className="v2-wallet-panel__title">
          {editing === "new" ? "Novo cartão" : "Editar cartão"}
        </h3>
        <PublishTargetForm
          initial={editing === "new" ? null : editing}
          onCancel={() => setEditing(null)}
          onSave={async (data) => {
            if (editing === "new") {
              await createPublishTarget(data);
            } else {
              await updatePublishTarget(editing.id, { label: data.label, config: data.config });
            }
            setEditing(null);
            await reload();
          }}
        />
      </div>
    );
  }

  return (
    <div className={`v2-wallet-panel${compact ? " v2-wallet-panel--compact" : ""}`}>
      <div className="v2-wallet-panel__head">
        <h3 className="v2-wallet-panel__title">Carteira de publicação</h3>
        <button type="button" className="v2-btn v2-btn--sm" onClick={() => setEditing("new")}>
          + Cartão
        </button>
      </div>
      {error && <p className="v2-error">{error}</p>}
      {loading && <p className="v2-card-meta">Carregando…</p>}
      {!loading && targets.length === 0 && (
        <p className="v2-card-meta">Nenhum destino configurado. Crie um cartão para conectar uma conta.</p>
      )}
      <div className="v2-wallet-stack">
        {targets.map((t, i) => (
          <PublishTargetCard
            key={t.id}
            target={t}
            stackIndex={i}
            selected={selectedTargetId === t.id}
            onSelect={onSelectTarget ? () => onSelectTarget(t.id) : undefined}
            onConnect={() => void handleConnect(t.id)}
            onDisconnect={() => void disconnectPublishTarget(t.id).then(reload)}
            onEdit={() => setEditing(t)}
            onDelete={() => void deletePublishTarget(t.id).then(reload)}
          />
        ))}
      </div>
    </div>
  );
}
