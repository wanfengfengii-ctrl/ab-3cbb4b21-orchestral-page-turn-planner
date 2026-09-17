import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Local dev proxy: the API is expected on the host's API_PORT (default 8080).
const apiTarget =
  process.env.API_PROXY_TARGET ??
  `http://localhost:${process.env.API_PORT ?? "8080"}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
