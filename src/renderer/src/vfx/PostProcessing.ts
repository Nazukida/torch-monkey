import { DefaultRenderingPipeline, Scene, Camera, Color4 } from '@babylonjs/core'
import type { PostProcessConfig } from '@shared/types/vfx'
import { DEFAULT_VFX_CONFIG } from '@shared/types/vfx'

/**
 * Post-processing stack: bloom (the dominant wotagei look — emissive glowsticks
 * blooming in a near-black venue), color grading, vignette, sharpen, optional DOF.
 */
export class PostProcessingStack {
  private pipeline: DefaultRenderingPipeline
  private config: PostProcessConfig
  private kimeTimer: ReturnType<typeof setTimeout> | null = null

  constructor(scene: Scene, camera: Camera, config: PostProcessConfig = DEFAULT_VFX_CONFIG.postProcess) {
    this.config = config
    this.pipeline = new DefaultRenderingPipeline('postProcess', true, scene, [camera])
    this.applyConfig(config)
  }

  applyConfig(config: PostProcessConfig): void {
    this.config = config
    const p = this.pipeline

    p.bloomEnabled = config.bloomEnabled
    p.bloomThreshold = config.bloomThreshold
    p.bloomWeight = config.bloomWeight
    p.bloomKernel = config.bloomKernel
    p.bloomScale = config.bloomScale

    p.imageProcessingEnabled = true
    p.imageProcessing.exposure = config.exposure
    p.imageProcessing.contrast = config.contrast

    p.imageProcessing.vignetteEnabled = config.vignetteEnabled
    p.imageProcessing.vignetteWeight = config.vignetteWeight
    p.imageProcessing.vignetteColor = new Color4(0, 0, 0, 0)

    p.sharpenEnabled = config.sharpenEnabled
    p.sharpen.edgeAmount = config.sharpenEdgeAmount
  }

  getConfig(): PostProcessConfig {
    return this.config
  }

  /** A kime punch: briefly spike bloom, then ease back. */
  triggerKimeEffect(): void {
    if (this.kimeTimer) clearTimeout(this.kimeTimer)
    this.pipeline.bloomWeight = Math.min(2.0, this.config.bloomWeight + 0.7)
    this.kimeTimer = setTimeout(() => {
      this.pipeline.bloomWeight = this.config.bloomWeight
      this.kimeTimer = null
    }, 300)
  }

  dispose(): void {
    if (this.kimeTimer) clearTimeout(this.kimeTimer)
    this.pipeline.dispose()
  }
}
