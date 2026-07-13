import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const appDomain = process.env.APP_DOMAIN ?? "localhost";

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: [appDomain, "localhost", "127.0.0.1"],
    proxy: {
      "/api": process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
      "/health": process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
    },
  },
});
