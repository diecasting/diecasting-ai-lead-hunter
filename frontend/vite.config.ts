import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend (FastAPI) runs on :8000. We proxy `/api` there so the browser
// does not need CORS and the dashboard works against a local server without
// configuring a separate origin. To point at a different backend, set
// VITE_API_BASE at build time, set VITE_PROXY_TARGET to override the dev
// proxy target (e.g. VITE_PROXY_TARGET=http://127.0.0.1:8001), or change the
// proxy target here.
const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
