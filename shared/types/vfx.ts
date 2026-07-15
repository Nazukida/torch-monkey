/**
 * VFX configuration: glowsticks + post-processing. Lives in its own decoupled
 * layer and is reused across characters / projects.
 */

export interface GlowstickOptions {
  /** Hex color. */
  color: string
  /** Emissive intensity multiplier (HDR >1 allowed). */
  intensity: number
  /** Length in meters (default 0.25). */
  length: number
  /** Radius in meters (default 0.015). */
  radius: number
  /** Point-light intensity on the body (0 to disable). */
  lightIntensity: number
  /** Optional angular offset in degrees (for double-wield). */
  offsetAngle?: number
}

export interface GlowstickConfig {
  enabled: boolean
  leftHand: GlowstickOptions
  rightHand: GlowstickOptions
  /** Wotagei double-wield: two sticks per hand. */
  doubleWield: boolean
  /** Ribbon trail enabled. */
  trail: boolean
}

export interface PostProcessConfig {
  bloomEnabled: boolean
  bloomThreshold: number
  bloomWeight: number
  bloomKernel: number
  bloomScale: number
  exposure: number
  contrast: number
  vignetteEnabled: boolean
  vignetteWeight: number
  sharpenEnabled: boolean
  sharpenEdgeAmount: number
}

export interface VFXConfig {
  glowstick: GlowstickConfig
  postProcess: PostProcessConfig
}

export const DEFAULT_GLOWSTICK_OPTIONS = (color: string): GlowstickOptions => ({
  color,
  intensity: 2.5,
  length: 0.25,
  radius: 0.015,
  lightIntensity: 0.5
})

export const DEFAULT_VFX_CONFIG: VFXConfig = {
  glowstick: {
    enabled: true,
    doubleWield: false,
    trail: true,
    leftHand: DEFAULT_GLOWSTICK_OPTIONS('#39ff14'),
    rightHand: DEFAULT_GLOWSTICK_OPTIONS('#00e5ff')
  },
  postProcess: {
    bloomEnabled: true,
    bloomThreshold: 0.6,
    bloomWeight: 0.8,
    bloomKernel: 64,
    bloomScale: 0.5,
    exposure: 1.0,
    contrast: 1.15,
    vignetteEnabled: true,
    vignetteWeight: 0.5,
    sharpenEnabled: true,
    sharpenEdgeAmount: 0.15
  }
}
