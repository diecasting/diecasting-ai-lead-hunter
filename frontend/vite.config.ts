import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend (FastAPI) runs on :8000. We proxy `/api` there so the browser
// does not need CORS and the dashboard works against a local server without
// configuring a separate origin. To point at a different backend, set
// VITE_API_BASE at build time or change the proxy target here.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
