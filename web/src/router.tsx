import { Navigate, Route, Routes } from "react-router-dom";
import LegacyApp from "./legacy/LegacyApp";
import { SystemDockProvider } from "./v2/components/SystemDock";
import { SystemStatusProvider } from "./v2/hooks/useSystemStatus";
import HomePage from "./v2/pages/HomePage";
import SearchPage from "./v2/pages/SearchPage";
import WatchPage from "./v2/pages/WatchPage";

export default function AppRouter() {
  return (
    <SystemStatusProvider>
      <SystemDockProvider>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/watch/:id" element={<WatchPage />} />
          <Route path="/old/*" element={<LegacyApp />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </SystemDockProvider>
    </SystemStatusProvider>
  );
}
