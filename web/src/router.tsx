import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { SystemDockProvider } from "./v2/components/SystemDock";
import { JobProvider } from "./v2/context/JobContext";
import { SystemStatusProvider } from "./v2/hooks/useSystemStatus";
import BayLayout from "./v2/layout/BayLayout";
import HomePage from "./v2/pages/HomePage";
import JobsPage from "./v2/pages/JobsPage";
import SearchPage from "./v2/pages/SearchPage";
import WatchPage from "./v2/pages/WatchPage";
import PublishWalletPage from "./v2/pages/PublishWalletPage";

function isBayPath(pathname: string): boolean {
  if (pathname === "/" || pathname === "/search") return true;
  if (pathname.startsWith("/watch/")) return true;
  return false;
}

/** Floating SystemDock only on full-page escape routes (not inside the bay). */
function SystemDockGate({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return <SystemDockProvider showDock={!isBayPath(pathname)}>{children}</SystemDockProvider>;
}

export default function AppRouter() {
  return (
    <SystemStatusProvider>
      <JobProvider>
        <SystemDockGate>
          <Routes>
            <Route element={<BayLayout />}>
              <Route path="/" element={<HomePage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/watch/:id" element={<WatchPage />} />
            </Route>
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/publish/wallet" element={<PublishWalletPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </SystemDockGate>
      </JobProvider>
    </SystemStatusProvider>
  );
}
