import { useState } from "react";
import {
  testPublishUpload,
  type PublishTarget,
  type PublishTestUploadResponse,
} from "../../api/v2";

const CHECK_LABEL: Record<string, string> = {
  channel: "Canal YouTube",
  upload_init: "Permissão de upload",
};

interface Props {
  target: PublishTarget;
  selected?: boolean;
  stackIndex?: number;
  onSelect?: () => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  connectDisabled?: boolean;
}

export default function PublishTargetCard({
  target,
  selected,
  stackIndex = 0,
  onSelect,
  onConnect,
  onDisconnect,
  onEdit,
  onDelete,
  connectDisabled,
}: Props) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<PublishTestUploadResponse | null>(null);

  const canConnect =
    (target.platform === "youtube" ||
      target.platform === "tiktok" ||
      target.platform === "instagram") &&
    target.oauth_configured;

  async function handleTestUpload(e: React.MouseEvent) {
    e.stopPropagation();
    if (!target.connected || target.platform !== "youtube") return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await testPublishUpload(target.id);
      setTestResult(res);
    } catch (err) {
      setTestResult({
        ok: false,
        checks: [
          {
            name: "error",
            ok: false,
            detail: err instanceof Error ? err.message : "Falha no teste",
          },
        ],
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <article
      className={`v2-wallet-card v2-wallet-card--${target.platform}${selected ? " v2-wallet-card--selected" : ""}`}
      style={{ "--stack-i": stackIndex } as React.CSSProperties}
      onClick={onSelect}
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
    >
      <span className={`v2-wallet-card__dot${target.connected ? " v2-wallet-card__dot--ok" : ""}`} />
      <span className={`v2-wallet-card__badge v2-wallet-card__badge--${target.platform}`}>
        {target.platform === "youtube" ? "YouTube" : target.platform === "tiktok" ? "TikTok" : "Instagram"}
      </span>
      <h3 className="v2-wallet-card__title">{target.label}</h3>
      <p className="v2-wallet-card__meta">
        {target.connected
          ? target.account_label || "Conectado"
          : target.oauth_configured
            ? "Não conectado"
            : "Configure OAuth no cartão"}
      </p>

      {testResult && (
        <div
          className={`v2-wallet-test${testResult.ok ? " v2-wallet-test--ok" : " v2-wallet-test--fail"}`}
          onClick={(e) => e.stopPropagation()}
        >
          <p className="v2-wallet-test__head">
            {testResult.ok ? "Upload OK" : "Upload com problemas"}
            {testResult.channel_title ? ` — ${testResult.channel_title}` : ""}
          </p>
          <ul className="v2-wallet-test__checks">
            {testResult.checks.map((c) => (
              <li key={c.name} className={c.ok ? "v2-wallet-test__check--ok" : "v2-wallet-test__check--fail"}>
                <span className="v2-wallet-test__dot" aria-hidden />
                <span>{CHECK_LABEL[c.name] ?? c.name}</span>
                <span className="v2-wallet-test__detail">{c.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="v2-wallet-card__actions" onClick={(e) => e.stopPropagation()}>
        {target.connected ? (
          <>
            <button type="button" className="v2-btn v2-btn--ghost v2-btn--sm" onClick={onDisconnect}>
              Desconectar
            </button>
            {target.platform === "youtube" && (
              <button
                type="button"
                className={`v2-btn v2-btn--sm v2-wallet-test-btn${testing ? " v2-wallet-test-btn--loading" : ""}`}
                disabled={testing}
                onClick={(e) => void handleTestUpload(e)}
              >
                {testing ? "Testando…" : "Testar upload"}
              </button>
            )}
          </>
        ) : (
          <button
            type="button"
            className="v2-btn v2-btn--sm"
            disabled={connectDisabled || !canConnect}
            onClick={onConnect}
            title={!target.oauth_configured ? "Configure Client ID e Secret no cartão" : undefined}
          >
            {canConnect ? "Conectar" : "Configure OAuth"}
          </button>
        )}
        {onEdit && (
          <button type="button" className="v2-btn v2-btn--ghost v2-btn--sm" onClick={onEdit}>
            Editar
          </button>
        )}
        {onDelete && (
          <button type="button" className="v2-btn v2-btn--ghost v2-btn--sm" onClick={onDelete}>
            Remover
          </button>
        )}
      </div>
    </article>
  );
}
