/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // All interfaces, not just loopback. Vite binds 127.0.0.1 by default, which makes the dev
    // server the one thing in the stack unreachable from another machine — every container port
    // is published on 0.0.0.0 — so it refuses connections over a LAN or Tailscale address.
    host: true,
    port: 8020,
    // Fail rather than drift. Vite's default is to walk up to the next free port, and 8021/8022
    // are the api and postgres, so a dev server left running from an earlier session silently
    // moved this one to 8023 — while run.sh still printed 8020 and playwright.config.ts still
    // pointed baseURL and webServer.url at 8020. A refusal names the problem; a quiet move sends
    // you to whatever is already on 8020.
    strictPort: true,
    proxy: {
      // Same-origin in production (Caddy); in dev the api container publishes 8000 on 8021.
      "/api": { target: "http://localhost:8021", changeOrigin: false },
    },
  },
  build: { outDir: "dist", sourcemap: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**"],
  },
});
