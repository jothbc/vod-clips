import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { SystemStatus } from "../../api/v2";
import { useSystemStatus } from "../hooks/useSystemStatus";
import DockTooltip from "./DockTooltip";
import GaugeMeter from "./GaugeMeter";

interface SystemDockContextValue {
  mobileOpen: boolean;
  toggleMobileOpen: () => void;
  setMobileOpen: (open: boolean) => void;
}

const SystemDockContext = createContext<SystemDockContextValue | null>(null);

export function useSystemDock(): SystemDockContextValue {
  const ctx = useContext(SystemDockContext);
  if (!ctx) {
    throw new Error("useSystemDock must be used within SystemDockProvider");
  }
  return ctx;
}

function formatGb(mb: number): string {
  return (mb / 1024).toFixed(1);
}

function HealthDot({ status, tooltip }: { status: "ok" | "warn" | "error"; tooltip: string }) {
  return (
    <DockTooltip text={tooltip} className={`v2-health-dot v2-health-dot--${status}`} role="status" aria-label={tooltip}>
      <span className="v2-health-dot-core" aria-hidden />
    </DockTooltip>
  );
}

function HealthDots({ data }: { data: SystemStatus }) {
  const whisperOk =
    data.whisper.configured_device !== "cuda" || data.whisper.effective_device === "cuda";
  const cudaOk = data.cuda.libs_available;
  const cudaTooltip = data.cuda.nvenc_available
    ? "CUDA libs: disponíveis · NVENC habilitado"
    : cudaOk
      ? "CUDA libs: disponíveis"
      : "CUDA libs: indisponíveis";

  return (
    <div className="v2-health-dots">
      <HealthDot
        status={data.ffmpeg ? "ok" : "error"}
        tooltip={data.ffmpeg ? "ffmpeg/ffprobe: instalado" : "ffmpeg/ffprobe: não encontrado"}
      />
      <HealthDot
        status={data.yt_dlp ? "ok" : "error"}
        tooltip={data.yt_dlp ? "yt-dlp: instalado" : "yt-dlp: não encontrado"}
      />
      <HealthDot
        status={data.ollama.available ? "ok" : "warn"}
        tooltip={
          data.ollama.available
            ? `Ollama: disponível (${data.ollama.host})`
            : `Ollama: indisponível (${data.ollama.host})`
        }
      />
      <HealthDot
        status={whisperOk ? "ok" : "warn"}
        tooltip={`Whisper ${data.whisper.model} (${data.whisper.effective_device})`}
      />
      <HealthDot status={cudaOk ? "ok" : "warn"} tooltip={cudaTooltip} />
    </div>
  );
}

function SystemDockContent() {
  const { data, error, indicator } = useSystemStatus();
  const { mobileOpen, setMobileOpen } = useSystemDock();

  let gaugeIndex = 0;

  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          className="v2-system-dock-backdrop"
          aria-label="Fechar painel do sistema"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={`v2-system-dock v2-system-dock--${indicator}${mobileOpen ? " v2-system-dock--open" : ""}`}
        aria-label="Status do sistema"
      >
        <div className="v2-system-dock-inner">
          <header className="v2-system-dock-head">
            <span className="v2-system-dock-mark" aria-hidden />
            <span className="v2-system-dock-title">SYS</span>
          </header>

          {error && <p className="v2-system-dock-error">{error}</p>}
          {!data && !error && (
            <div className="v2-system-dock-loading" aria-label="Carregando">
              <span className="v2-system-dock-pulse" />
            </div>
          )}

          {data && (
            <>
              <div className="v2-system-dock-gauges">
                {data.cpu && (
                  <GaugeMeter
                    label="CPU"
                    percent={data.cpu.percent}
                    tooltip={`Uso da CPU (${data.cpu.count} threads): ${data.cpu.percent.toFixed(0)}%`}
                    index={gaugeIndex++}
                  />
                )}
                {data.memory && (
                  <GaugeMeter
                    label="RAM"
                    percent={data.memory.percent}
                    tooltip={`Memória RAM: ${formatGb(data.memory.used_mb)} / ${formatGb(data.memory.total_mb)} GB (${data.memory.percent.toFixed(0)}%)`}
                    index={gaugeIndex++}
                  />
                )}
                {data.gpu?.utilization_percent != null && (
                  <GaugeMeter
                    label="GPU"
                    percent={data.gpu.utilization_percent}
                    tooltip={`Utilização da GPU (${data.gpu.name}): ${data.gpu.utilization_percent.toFixed(0)}%`}
                    index={gaugeIndex++}
                  />
                )}
                {data.gpu && data.gpu.memory_total_mb > 0 && (
                  <GaugeMeter
                    label="VRAM"
                    percent={(data.gpu.memory_used_mb / data.gpu.memory_total_mb) * 100}
                    tooltip={`VRAM: ${formatGb(data.gpu.memory_used_mb)} / ${formatGb(data.gpu.memory_total_mb)} GB (${((data.gpu.memory_used_mb / data.gpu.memory_total_mb) * 100).toFixed(0)}%)`}
                    index={gaugeIndex++}
                  />
                )}
                {data.active_job && (
                  <GaugeMeter
                    label="JOB"
                    percent={data.active_job.percent}
                    tooltip={`Job: ${data.active_job.feature} — ${data.active_job.phase} — ${data.active_job.message}`}
                    index={gaugeIndex++}
                  />
                )}
              </div>

              <div className="v2-system-dock-foot">
                <HealthDots data={data} />
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

export function SystemDockProvider({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const toggleMobileOpen = useCallback(() => setMobileOpen((o) => !o), []);

  return (
    <SystemDockContext.Provider value={{ mobileOpen, toggleMobileOpen, setMobileOpen }}>
      {children}
      <SystemDockContent />
    </SystemDockContext.Provider>
  );
}
