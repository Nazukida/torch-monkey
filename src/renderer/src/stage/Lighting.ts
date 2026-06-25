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
  private config: LightConfig

  constructor(scene: Scene, config: LightConfig = DEFAULT_LIGHT_CONFIG) {
    this.scene = scene
    this.config = config

    this.ambient = new HemisphericLight('ambient', new Vector3(0, 1, 0), scene)
    this.ambient.intensity = config.ambientIntensity
    this.ambient.diffuse = new Color3(0.1, 0.1, 0.15)
    this.ambient.groundColor = new Color3(0.02, 0.02, 0.03)

    this.rim = new DirectionalLight('rim', new Vector3(0, 0.3, -1), scene)
    this.rim.intensity = config.rimLightIntensity
    this.rim.diffuse = new Color3(0.3, 0.4, 0.6)

    this.buildSpotLights(config.spotLights)
  }

  private buildSpotLights(specs: SpotLightConfig[]): void {
    for (const s of this.spotLights) s.dispose()
    this.spotLights = []
    this.shadowGenerator?.dispose()
    this.shadowGenerator = null

    specs.forEach((spec, i) => {
      const spot = new SpotLight(
        `spot_${i}`,
        new Vector3(...spec.position),
        new Vector3(...spec.direction),
        spec.angle,
        0.1,
        this.scene
      )
      spot.intensity = spec.intensity
      spot.diffuse = hexToColor3(spec.color)
      spot.shadowEnabled = spec.shadowEnabled
      spot.shadowMinZ = 1
      spot.shadowMaxZ = 30
      this.spotLights.push(spot)

      if (spec.shadowEnabled && !this.shadowGenerator) {
        // 2048 map is plenty for a small stage and keeps perf in check.
        this.shadowGenerator = new ShadowGenerator(2048, spot)
        this.shadowGenerator.useExponentialShadowMap = true
        this.shadowGenerator.usePoissonSampling = true
      }
    })
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
