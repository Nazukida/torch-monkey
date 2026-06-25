/**
 * Stage configuration & lighting types.
 * Shared between the renderer (Babylon scene), the stores, and the project file format.
 */

export type FloorMode = 'grid' | 'solid' | 'reflective'

export interface StageConfig {
  /** Stage width in meters. Default 10, range 5–50. */
  width: number
  /** Stage depth in meters. Default 10, range 5–50. */
  depth: number
  floorMode: FloorMode
  /** Hex color string, e.g. '#15151f'. */
  floorColor: string
  showGrid: boolean
  /** Scene clear color (background), hex string. */
  backgroundColor: string
}

export interface SpotLightConfig {
  position: [number, number, number]
  direction: [number, number, number]
  /** Cone half-angle in radians. Default π/4. */
  angle: number
  intensity: number
  /** Hex color string. */
  color: string
  shadowEnabled: boolean
}

export interface LightConfig {
  /** Ambient (hemispheric) intensity, 0–1. Default 0.05 — dark venue. */
  ambientIntensity: number
  spotLights: SpotLightConfig[]
  /** Rim / back light intensity, 0–1. Default 0.3. */
  rimLightIntensity: number
}

/** What gets persisted into a project file. */
export interface ProjectStageData {
  stage: StageConfig
  lighting: LightConfig
}

export const DEFAULT_STAGE_CONFIG: StageConfig = {
  width: 10,
  depth: 10,
  floorMode: 'grid',
  floorColor: '#15151f',
  showGrid: true,
  backgroundColor: '#050510'
}

export const DEFAULT_LIGHT_CONFIG: LightConfig = {
  ambientIntensity: 0.05,
  rimLightIntensity: 0.3,
  spotLights: [
    {
      position: [0, 8, 5],
      direction: [0, -1, -0.5],
      angle: Math.PI / 4,
      intensity: 2.0,
      color: '#fff2cc',
      shadowEnabled: true
    }
  ]
}
