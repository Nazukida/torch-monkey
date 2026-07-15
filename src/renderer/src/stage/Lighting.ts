import {
  Scene,
  HemisphericLight,
  SpotLight,
  DirectionalLight,
  Vector3,
  Color3,
  ShadowGenerator
} from '@babylonjs/core'
import type { LightConfig, SpotLightConfig } from '@shared/types/stage'
import { DEFAULT_LIGHT_CONFIG } from '@shared/types/stage'

function hexToColor3(hex: string): Color3 {
  const m = hex.replace('#', '')
  return new Color3(
    parseInt(m.substring(0, 2), 16) / 255,
    parseInt(m.substring(2, 4), 16) / 255,
    parseInt(m.substring(4, 6), 16) / 255
  )
}

/**
 * Dark-venue lighting rig: a faint hemispheric ambient, one or more overhead
 * spot lights (the stage key light, with shadows), and a cool rim/back light to
 * separate the character silhouette from the black background.
 */
export class Lighting {
  private scene: Scene
  private ambient: HemisphericLight
  private spotLights: SpotLight[] = []
  private rim: DirectionalLight
  private shadowGenerator: ShadowGenerator | null = null
  /** The spot the persistent ShadowGenerator is bound to (null iff no shadows). */
  private shadowCaster: SpotLight | null = null
  private config: LightConfig

  constructor(scene: Scene, config: LightConfig = DEFAULT_LIGHT_CONFIG) {
    this.scene = scene
    this.config = config

    this.ambient = new HemisphericLight('ambient', new Vector3(0, 1, 0), scene)
    this.ambient.intensity = config.ambientIntensity
    // White diffuse so the ambient slider's intensity maps linearly to fill
    // brightness — a dark fixed diffuse (0.1,0.1,0.15) previously capped the
    // slider's visible effect near zero.
    this.ambient.diffuse = Color3.White()
    this.ambient.groundColor = new Color3(0.05, 0.05, 0.08)

    this.rim = new DirectionalLight('rim', new Vector3(0, 0.3, -1), scene)
    this.rim.intensity = config.rimLightIntensity
    this.rim.diffuse = Color3.White()

    this.buildSpotLights(config.spotLights)
  }

  /**
   * Apply the spot-light spec IN PLACE. Existing SpotLights are mutated
   * (intensity, colour, position, direction, angle, shadowEnabled) rather than
   * disposed+recreated, so the single persistent ShadowGenerator — and the
   * shadow casters registered on it at init — survive every slider edit. The
   * previous dispose+rebuild path tore down the live shadow rig on every store
   * mutation (double-disposing the ShadowGenerator via Light.dispose), which
   * collapsed the frame to black after the first lighting toggle and made
   * further slider edits not visibly apply. SpotLights are only added/removed
   * when the configured count changes, and the ShadowGenerator is (re)created
   * lazily iff some spot wants shadows and torn down iff none does.
   */
  private buildSpotLights(specs: SpotLightConfig[]): void {
    // Update existing slots in place; create new spots for any surplus.
    for (let i = 0; i < specs.length; i++) {
      const spec = specs[i]
      let spot = this.spotLights[i]
      if (!spot) {
        spot = new SpotLight(
          `spot_${i}`,
          new Vector3(spec.position[0], spec.position[1], spec.position[2]),
          new Vector3(spec.direction[0], spec.direction[1], spec.direction[2]),
          spec.angle,
          0.1,
          this.scene
        )
        spot.shadowMinZ = 1
        spot.shadowMaxZ = 30
        this.spotLights.push(spot)
      } else {
        spot.position.set(spec.position[0], spec.position[1], spec.position[2])
        spot.direction = new Vector3(spec.direction[0], spec.direction[1], spec.direction[2])
        spot.angle = spec.angle
      }
      spot.intensity = spec.intensity
      spot.diffuse = hexToColor3(spec.color)
      spot.shadowEnabled = spec.shadowEnabled
    }

    // Trim surplus spots if the config shrank. If the bound shadow caster is
    // among them, dispose the ShadowGenerator BEFORE the light — Light.dispose()
    // itself disposes its bound ShadowGenerator, so disposing the generator first
    // avoids a destabilising double-dispose.
    while (this.spotLights.length > specs.length) {
      const removed = this.spotLights.pop() as SpotLight
      if (removed === this.shadowCaster) {
        this.shadowGenerator?.dispose()
        this.shadowGenerator = null
        this.shadowCaster = null
      }
      removed.dispose()
    }

    // Reconcile the ShadowGenerator with the shadow-enabled state: keep exactly
    // one persistent generator bound to the first shadow-casting spot.
    const caster = this.spotLights.find((s) => s.shadowEnabled) ?? null
    if (caster && !this.shadowGenerator) {
      this.shadowGenerator = new ShadowGenerator(2048, caster)
      this.shadowGenerator.useExponentialShadowMap = true
      this.shadowGenerator.usePoissonSampling = true
      this.shadowCaster = caster
    } else if (!caster && this.shadowGenerator) {
      this.shadowGenerator.dispose()
      this.shadowGenerator = null
      this.shadowCaster = null
    }
  }

  updateFromConfig(config: LightConfig): void {
    this.config = config
    this.ambient.intensity = config.ambientIntensity
    this.rim.intensity = config.rimLightIntensity
    this.buildSpotLights(config.spotLights)
  }

  getConfig(): LightConfig {
    return this.config
  }

  getShadowGenerator(): ShadowGenerator | null {
    return this.shadowGenerator
  }

  dispose(): void {
    for (const s of this.spotLights) s.dispose()
    this.shadowGenerator?.dispose()
    this.ambient.dispose()
    this.rim.dispose()
  }
}
