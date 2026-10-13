import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8010",
      "/health": "http://127.0.0.1:8010",
      "/docs": "http://127.0.0.1:8010",
      "/openapi.json": "http://127.0.0.1:8010",
    },
  },
});
