import { resolve } from "path";

import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
// vitest/config re-exports Vite's defineConfig with the `test` property's
// types merged in -- this is the one config file both `vite build` and
// `vitest run` read (docs/development/TESTING.md).
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // PR25E S6: never reload on a new service worker by itself (design 13.3).
      registerType: "prompt",
      includeAssets: ["icons/icon-192.png", "icons/icon-512.png"],
      manifest: {
        name: "Medical Equipment Pool",
        short_name: "MEP",
        description: "ระบบรับ-ส่งเครื่องมือแพทย์",
        theme_color: "#2563EB",
        background_color: "#0B1220",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
      workbox: {
        // Never serve the SPA shell for API calls (a cached index.html answer
        // would look like a successful API response).
        navigateFallbackDenylist: [/^\/api\//],
        globPatterns: ["**/*.{js,css,html,svg,png,ico}"],
        // PR25E S4: no runtime caching of API responses. Offline reads come
        // from the IndexedDB reference snapshot (src/offline/snapshot.ts); a
        // generic NetworkFirst cache of /equipment and /dashboard answers
        // would serve stale server data with no staleness signal and leave
        // data behind on a shared device.
      },
    }),
  ],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom", "zustand", "@tanstack/react-query"],
          charts: ["recharts"],
          scanner: ["@zxing/browser", "@zxing/library"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: false,
  },
});
