import { resolve } from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { rendererAliases } from './vite.shared'

/**
 * Plain-web build of the renderer — no Electron involved. Produces a static
 * bundle the FastAPI server serves at "/" (output → python/web_dist/), so the
 * browser app and the API share one origin (no CORS). At runtime, main.tsx
 * detects the absence of `window.electronAPI` and swaps in the HTTP-backed shim
 * (src/renderer/src/web/apiShim.ts), letting the renderer run unchanged.
 *
 *   npm run build:web   # production bundle → python/web_dist/
 *   npm run dev:web     # vite dev server at :5173 with /api proxied to :19876
 */
export default defineConfig({
  root: resolve(__dirname, 'src/renderer'),
  base: '/',
  resolve: { alias: rendererAliases },
  plugins: [react(), tailwindcss()],
  build: {
    outDir: resolve(__dirname, 'python/web_dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: { index: resolve(__dirname, 'src/renderer/index.html') }
    }
  },
  server: {
    port: 5173,
    // Proxy API calls to the Python pipeline server during browser dev.
    proxy: {
      '/api': 'http://127.0.0.1:19876'
    }
  }
})
