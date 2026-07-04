import { useEffect, useState } from "react";
import {
  fetchPublishOAuthDefaults,
  type PublishPlatform,
  type PublishTarget,
} from "../../api/v2";

interface Props {
  initial?: PublishTarget | null;
  onSave: (data: {
    label: string;
    platform: PublishPlatform;
    config: Record<string, unknown>;
  }) => void | Promise<void>;
  onCancel: () => void;
}

const OAUTH_HELP: Record<
  PublishPlatform,
  { title: string; steps: string[]; consoleUrl: string; idLabel: string; secretLabel: string }
> = {
  youtube: {
    title: "App OAuth do Google (YouTube Data API)",
    idLabel: "Client ID",
    secretLabel: "Client Secret",
    consoleUrl: "https://console.cloud.google.com/apis/credentials",
    steps: [
      "Abra Google Cloud Console → APIs e serviços → Credenciais.",
      "Crie um ID do cliente OAuth (tipo Aplicativo da Web).",
      "Em URIs de redirecionamento autorizados, adicione a URL abaixo.",
      "Ative a YouTube Data API v3 no projeto.",
      "Cole Client ID e Client Secret aqui — ficam salvos criptografados no SQLite local (temp/).",
    ],
  },
  tiktok: {
    title: "App OAuth do TikTok",
    idLabel: "Client Key",
    secretLabel: "Client Secret",
    consoleUrl: "https://developers.tiktok.com/",
    steps: [
      "Crie um app em TikTok for Developers com permissão de upload.",
      "Configure o Redirect URI abaixo no painel do app.",
      "Cole Client Key e Client Secret aqui.",
    ],
  },
  instagram: {
    title: "App OAuth da Meta (Instagram)",
    idLabel: "App ID",
    secretLabel: "App Secret",
    consoleUrl: "https://developers.facebook.com/apps/",
    steps: [
      "Crie um app Meta com Instagram Graph API.",
      "Adicione o Redirect URI abaixo em Facebook Login → Configurações.",
      "Cole App ID e App Secret aqui.",
    ],
  },
};

export default function PublishTargetForm({ initial, onSave, onCancel }: Props) {
  const [label, setLabel] = useState(initial?.label ?? "");
  const [platform, setPlatform] = useState<PublishPlatform>(initial?.platform ?? "youtube");
  const [privacy, setPrivacy] = useState(String(initial?.config?.privacy ?? "unlisted"));
  const [categoryId, setCategoryId] = useState(String(initial?.config?.category_id ?? "20"));
  const [oauthClientId, setOauthClientId] = useState(String(initial?.config?.oauth_client_id ?? ""));
  const [oauthClientSecret, setOauthClientSecret] = useState("");
  const [oauthRedirect, setOauthRedirect] = useState(
    String(initial?.config?.oauth_redirect_uri ?? "")
  );
  const [defaultRedirects, setDefaultRedirects] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void fetchPublishOAuthDefaults()
      .then((res) => setDefaultRedirects(res.redirect_uris))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!oauthRedirect && defaultRedirects[platform]) {
      setOauthRedirect(defaultRedirects[platform]);
    }
  }, [platform, defaultRedirects, oauthRedirect]);

  const help = OAUTH_HELP[platform];
  const redirectUri = oauthRedirect || defaultRedirects[platform] || "";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!label.trim()) return;
    setBusy(true);
    try {
      const config: Record<string, unknown> = { ...(initial?.config ?? {}) };
      if (platform === "youtube") {
        config.privacy = privacy;
        config.category_id = categoryId;
      }
      config.oauth_client_id = oauthClientId.trim();
      config.oauth_redirect_uri = redirectUri.trim();
      if (oauthClientSecret.trim()) {
        config.oauth_client_secret = oauthClientSecret.trim();
      }
      await onSave({ label: label.trim(), platform, config });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="v2-wallet-form" onSubmit={(e) => void handleSubmit(e)}>
      <label>
        Nome do cartão
        <input value={label} onChange={(e) => setLabel(e.target.value)} required maxLength={120} />
      </label>
      <label>
        Plataforma
        <select
          value={platform}
          disabled={!!initial}
          onChange={(e) => setPlatform(e.target.value as PublishPlatform)}
        >
          <option value="youtube">YouTube</option>
          <option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option>
        </select>
      </label>

      {platform === "youtube" && (
        <>
          <label>
            Privacidade padrão
            <select value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
              <option value="public">Público</option>
              <option value="unlisted">Não listado</option>
              <option value="private">Privado</option>
            </select>
          </label>
          <label>
            Categoria (ID)
            <input value={categoryId} onChange={(e) => setCategoryId(e.target.value)} />
          </label>
        </>
      )}

      <section className="v2-wallet-oauth">
        <h4 className="v2-wallet-oauth__title">{help.title}</h4>
        <ol className="v2-wallet-oauth__steps">
          {help.steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
        <a
          href={help.consoleUrl}
          target="_blank"
          rel="noreferrer"
          className="v2-wallet-oauth__link"
        >
          Abrir console do desenvolvedor
        </a>

        <label>
          {help.idLabel}
          <input
            value={oauthClientId}
            onChange={(e) => setOauthClientId(e.target.value)}
            placeholder="xxxx.apps.googleusercontent.com"
            autoComplete="off"
          />
        </label>
        <label>
          {help.secretLabel}
          <input
            type="password"
            value={oauthClientSecret}
            onChange={(e) => setOauthClientSecret(e.target.value)}
            placeholder={initial?.oauth_configured ? "•••••••• (deixe vazio para manter)" : ""}
            autoComplete="new-password"
          />
        </label>
        <label>
          Redirect URI (copie para o console)
          <div className="v2-wallet-oauth__redirect">
            <input value={redirectUri} readOnly />
            <button
              type="button"
              className="v2-btn v2-btn--sm"
              onClick={() => void navigator.clipboard.writeText(redirectUri)}
            >
              Copiar
            </button>
          </div>
        </label>
        {initial?.oauth_configured && !oauthClientSecret && (
          <p className="v2-card-meta">Secret já salvo neste cartão.</p>
        )}
      </section>

      <div className="v2-modal-actions">
        <button type="button" className="v2-btn v2-btn--ghost" onClick={onCancel}>
          Cancelar
        </button>
        <button type="submit" className="v2-btn v2-btn--primary" disabled={busy}>
          {busy ? "Salvando…" : initial ? "Atualizar" : "Criar cartão"}
        </button>
      </div>
    </form>
  );
}
