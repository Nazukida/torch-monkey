import { Engine, Scene, Color4, Color3 } from '@babylonjs/core'

/**
 * Babylon.js engine singleton.
 *
 * Owns the WebGL Engine, the main Scene, and the per-frame update registry.
 * Subsystems (Stage3D, MotionPlayer, GlowstickVFX, …) register an `update`
 * callback instead of calling `scene.registerBeforeRender` directly, so we keep
 * a single deterministic update order and can tear everything down cleanly.
 */
export type FrameUpdateCallback = (deltaSeconds: number, totalSeconds: number) => void

class BabylonEngineImpl {
  engine: Engine | null = null
  scene: Scene | null = null
  canvas: HTMLCanvasElement | null = null

  private updateCallbacks = new Set<FrameUpdateCallback>()
  private initialized = false
  private lastTimeMs = 0

  getInstance(): BabylonEngineImpl {
    return this
  }

  async initialize(canvas: HTMLCanvasElement): Promise<void> {
    if (this.initialized && this.engine) return

    this.canvas = canvas
    this.engine = new Engine(canvas, true, {
      preserveDrawingBuffer: true, // needed for video export (readPixels)
      stencil: true, // advanced shadows
      antialias: true,
      powerPreference: 'high-performance'
    })

    const scene = new Scene(this.engine)
    // Very dark blue — the wotagei venue look. Color is overridable from StageConfig.
    scene.clearColor = new Color4(0.02, 0.02, 0.05, 1.0)
    scene.ambientColor = new Color3(0.05, 0.05, 0.08)
    scene.collisionsEnabled = true
    scene.skipPointerMovePicking = true
    this.scene = scene

    this.lastTimeMs = performance.now()
    this.engine.runRenderLoop(() => {
      const now = performance.now()
      const delta = Math.min(0.1, (now - this.lastTimeMs) / 1000) // clamp big gaps
      this.lastTimeMs = now
      for (const cb of this.updateCallbacks) {
        try {
          cb(delta, now / 1000)
        } catch (err) {
          // A misbehaving callback must not kill the render loop.
          console.error('[BabylonEngine] update callback threw:', err)
        }
      }
      scene.render()
    })

    window.addEventListener('resize', this.resize)
    this.initialized = true
  }

  /** Register a per-frame update. Returns a disposer. */
  registerBeforeUpdate(cb: FrameUpdateCallback): () => void {
    this.updateCallbacks.add(cb)
    return () => this.updateCallbacks.delete(cb)
  }

  resize = (): void => {
    this.engine?.resize()
  }

  get isReady(): boolean {
    return this.initialized && !!this.engine && !!this.scene
  }

  dispose(): void {
    window.removeEventListener('resize', this.resize)
    this.updateCallbacks.clear()
    this.scene?.dispose()
    this.engine?.dispose()
    this.scene = null
    this.engine = null
    this.canvas = null
    this.initialized = false
  }
}

export const BabylonEngine = new BabylonEngineImpl()
export default BabylonEngine
