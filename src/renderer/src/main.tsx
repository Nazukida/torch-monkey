import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

/**
 * Boot the renderer under either backend.
 *
 * Under Electron the preload script injects `window.electronAPI` (IPC bridge).
 * In a plain browser there is no preload, so we swap in the HTTP-backed shim
 * (`./web/apiShim`) that talks to the FastAPI server. The renderer itself is
 * identical in both cases — this is the only fork. The dynamic import keeps the
 * shim out of the Electron bundle's hot path (it's never executed there).
 */
async function bootstrap(): Promise<void> {
  const w = window as Window & { electronAPI?: unknown }
  if (!w.electronAPI) {
    const { webAPI } = await import('./web/apiShim')
    w.electronAPI = webAPI
  }

  const container = document.getElementById('root')
  if (!container) throw new Error('Root container #root not found')
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>
  )
}

void bootstrap()
