import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = (env.VITE_API_PROXY_TARGET || env.VITE_API_BASE || "http://127.0.0.1:8000").replace(
    /\/$/,
    ""
  );

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        "/media": {
          target: apiTarget,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
      },
    },
  };
});
