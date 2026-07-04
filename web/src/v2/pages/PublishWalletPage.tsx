import AppHeader from "../components/AppHeader";
import PublishWalletPanel from "../components/PublishWalletPanel";
import "../v2.css";

export default function PublishWalletPage() {
  return (
    <div className="v2-root">
      <div className="v2-shell">
        <AppHeader />
        <main className="v2-wallet-page">
          <header className="v2-wallet-page__hero">
            <h1 className="v2-wallet-page__title">Carteira de publicação</h1>
            <p className="v2-wallet-page__sub">
              Destinos de deploy — conecte contas e publique clips sem sair do estúdio.
            </p>
          </header>
          <PublishWalletPanel />
        </main>
      </div>
    </div>
  );
}
