import { resolve } from 'path'

/**
 * Renderer path aliases shared by the Electron build (electron.vite.config.ts)
 * and the plain-web build (vite.config.web.ts). Defining them once here prevents
 * the two builds from drifting on `@shared` / `@renderer` resolution — the
 * renderer imports the same module specifiers regardless of which backend
 * (preload bridge vs HTTP shim) it is bundled against.
 */
export const rendererAliases = {
  '@shared': resolve(__dirname, 'shared'),
  '@renderer': resolve(__dirname, 'src/renderer/src')
}
