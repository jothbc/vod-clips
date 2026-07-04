import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useSystemStatus } from "../hooks/useSystemStatus";
import { useSystemDock } from "./SystemDock";

interface Props {
  onOpenGallery?: () => void;
}

export default function AppHeader({ onOpenGallery }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useState("");
  const { indicator } = useSystemStatus();
  const { toggleMobileOpen } = useSystemDock();

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
    <header className="v2-header">
      <Link to="/" className="v2-logo">
        Reels<span>.</span>
      </Link>
      <form className="v2-search" onSubmit={handleSearch} role="search">
        <input
          type="search"
          placeholder="Buscar vídeos e clipes…"
          aria-label="Buscar vídeos e clipes"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </form>
      <div className="v2-header-actions">
        <button
          type="button"
          className={`v2-btn v2-system-btn v2-system-btn--mobile v2-system-btn--${indicator}`}
          onClick={toggleMobileOpen}
          title="Status do sistema"
        >
          <span className="v2-system-dot" />
          Sistema
        </button>
        {onOpenGallery && (
          <button type="button" className="v2-btn v2-btn--primary" onClick={onOpenGallery}>
            Galeria
          </button>
        )}
        <Link to="/publish/wallet" className="v2-btn v2-btn--ghost">
          Carteira
        </Link>
        <Link to="/old" className="v2-btn v2-btn--ghost">
          UI legada
        </Link>
      </div>
    </header>
  );
}
