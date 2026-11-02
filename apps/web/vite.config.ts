import { fileURLToPath, URL } from "node:url"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  // Isolate this UI's assets from legacy CDN entries that cached SPA fallback HTML at image URLs.
  build: { assetsDir: "assets/portal-ui-v1" },
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url))
    },
    extensions: [".ts", ".tsx", ".js", ".jsx", ".json", ".mjs"]
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      },
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      },
      "/exports": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
})
