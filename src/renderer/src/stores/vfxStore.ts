import { create } from 'zustand'
import type { VFXConfig, GlowstickConfig, PostProcessConfig } from '@shared/types/vfx'
import { DEFAULT_VFX_CONFIG } from '@shared/types/vfx'

interface VFXState {
  config: VFXConfig

  setGlowEnabled: (v: boolean) => void
  setGlowColor: (side: 'left' | 'right', hex: string) => void
  setGlowIntensity: (side: 'left' | 'right', v: number) => void
  setTrailEnabled: (v: boolean) => void
  setDoubleWield: (v: boolean) => void
  setLightIntensity: (side: 'left' | 'right', v: number) => void

  setPost: (partial: Partial<PostProcessConfig>) => void
  applyGlow: (partial: Partial<GlowstickConfig>) => void

  loadFromProject: (cfg: VFXConfig) => void
  toJSON: () => VFXConfig
}

export const useVfxStore = create<VFXState>((set, get) => ({
  config: structuredClone(DEFAULT_VFX_CONFIG),

  setGlowEnabled: (v) =>
    set((s) => ({ config: { ...s.config, glowstick: { ...s.config.glowstick, enabled: v } } })),
  setGlowColor: (side, hex) =>
    set((s) => ({
      config: {
        ...s.config,
        glowstick: {
          ...s.config.glowstick,
          [side === 'left' ? 'leftHand' : 'rightHand']: {
            ...s.config.glowstick[side === 'left' ? 'leftHand' : 'rightHand'],
            color: hex
          }
        }
      }
    })),
  setGlowIntensity: (side, v) =>
    set((s) => ({
      config: {
        ...s.config,
        glowstick: {
          ...s.config.glowstick,
          [side === 'left' ? 'leftHand' : 'rightHand']: {
            ...s.config.glowstick[side === 'left' ? 'leftHand' : 'rightHand'],
            intensity: v
          }
        }
      }
    })),
  setTrailEnabled: (v) =>
    set((s) => ({ config: { ...s.config, glowstick: { ...s.config.glowstick, trail: v } } })),
  setDoubleWield: (v) =>
    set((s) => ({ config: { ...s.config, glowstick: { ...s.config.glowstick, doubleWield: v } } })),
  setLightIntensity: (side, v) =>
    set((s) => ({
      config: {
        ...s.config,
        glowstick: {
          ...s.config.glowstick,
          [side === 'left' ? 'leftHand' : 'rightHand']: {
            ...s.config.glowstick[side === 'left' ? 'leftHand' : 'rightHand'],
            lightIntensity: v
          }
        }
      }
    })),

  setPost: (partial) =>
    set((s) => ({ config: { ...s.config, postProcess: { ...s.config.postProcess, ...partial } } })),
  applyGlow: (partial) =>
    set((s) => ({ config: { ...s.config, glowstick: { ...s.config.glowstick, ...partial } } })),

  loadFromProject: (cfg) => set({ config: structuredClone(cfg) }),
  toJSON: () => structuredClone(get().config)
}))
