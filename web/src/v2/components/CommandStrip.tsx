import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useBay } from "../context/BayContext";
import { useJobs } from "../context/JobContext";
import { useSystemStatus } from "../hooks/useSystemStatus";

export default function CommandStrip() {
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useState("");
  const { indicator } = useSystemStatus();
  const { activeJobs } = useJobs();
  const { toggleRail, toggleOps, openGallery } = useBay();

  useEffect(() => {
    if (location.pathname === "/search") {
      setQuery(new URLSearchParams(location.search).get("q") ?? "");
      return;
    }
    setQuery("");
  }, [location.pathname, location.search]);

  function handleSearch(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) {
      if (location.pathname === "/search") navigate("/");
      return;
    }
    navigate(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <header className="v2-command">
      <button
        type="button"
        className="v2-btn v2-command-drawer-btn v2-command-drawer-btn--rail"
        onClick={toggleRail}
        aria-label="Abrir lista de mídia"
      >
        Mídia
      </button>
      <Link to="/" className="v2-logo">
        Reels<span>.</span>
      </Link>
      <form className="v2-command-search" onSubmit={handleSearch} role="search">
        <input
          type="search"
          placeholder="Buscar vídeos e clipes…"
          aria-label="Buscar vídeos e clipes"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </form>
      <div className="v2-command-actions">
        <span
          className={`v2-command-pill v2-command-pill--${indicator}`}
          title="Status do sistema"
        >
          sys {indicator}
        </span>
        <button type="button" className="v2-btn v2-btn--primary" onClick={openGallery}>
          Galeria
        </button>
        <Link to="/jobs" className="v2-btn v2-btn--ghost v2-jobs-link">
          Jobs
          {activeJobs.length > 0 && <span className="v2-jobs-badge">{activeJobs.length}</span>}
        </Link>
        <Link to="/publish/wallet" className="v2-btn v2-btn--ghost">
          Carteira
        </Link>
        <button
          type="button"
          className="v2-btn v2-command-drawer-btn v2-command-drawer-btn--ops"
          onClick={toggleOps}
          aria-label="Abrir painel de ops"
        >
          Ops
        </button>
      </div>
    </header>
  );
}
