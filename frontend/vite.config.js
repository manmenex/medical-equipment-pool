import { resolve } from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";
export default defineConfig({
    plugins: [
        react(),
        VitePWA({
            registerType: "autoUpdate",
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
                globPatterns: ["**/*.{js,css,html,svg,png,ico}"],
                runtimeCaching: [
                    {
                        urlPattern: /\/api\/v1\/(equipment|dashboard)/,
                        handler: "NetworkFirst",
                        options: {
                            cacheName: "mep-api-cache",
                            networkTimeoutSeconds: 3,
                            expiration: { maxEntries: 500, maxAgeSeconds: 300 },
                        },
                    },
                ],
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
});
