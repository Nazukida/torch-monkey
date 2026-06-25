import { create } from 'zustand'
import type {
  StageConfig,
  LightConfig,
  SpotLightConfig,
  FloorMode,
  ProjectStageData
} from '@shared/types/stage'
import { DEFAULT_STAGE_CONFIG, DEFAULT_LIGHT_CONFIG } from '@shared/types/stage'

interface StageState {
  config: StageConfig
  lightConfig: LightConfig

  setWidth: (w: number) => void
  setDepth: (d: number) => void
  setFloorMode: (m: FloorMode) => void
  setFloorColor: (hex: string) => void
  setBackgroundColor: (hex: string) => void
  setShowGrid: (show: boolean) => void

  setAmbientIntensity: (v: number) => void
  setRimIntensity: (v: number) => void
  setSpotIntensity: (index: number, v: number) => void
  setSpot: (index: number, partial: Partial<SpotLightConfig>) => void
  updateLightConfig: (partial: Partial<LightConfig>) => void

  loadFromProject: (data: ProjectStageData) => void
  toJSON: () => ProjectStageData
}

export const useStageStore = create<StageState>((set, get) => ({
  config: { ...DEFAULT_STAGE_CONFIG },
  lightConfig: {
    ...DEFAULT_LIGHT_CONFIG,
    spotLights: DEFAULT_LIGHT_CONFIG.spotLights.map((s) => ({ ...s }))
  },

  setWidth: (w) => set((s) => ({ config: { ...s.config, width: clamp(w, 5, 50) } })),
  setDepth: (d) => set((s) => ({ config: { ...s.config, depth: clamp(d, 5, 50) } })),
  setFloorMode: (m) => set((s) => ({ config: { ...s.config, floorMode: m } })),
  setFloorColor: (hex) => set((s) => ({ config: { ...s.config, floorColor: hex } })),
  setBackgroundColor: (hex) => set((s) => ({ config: { ...s.config, backgroundColor: hex } })),
  setShowGrid: (show) => set((s) => ({ config: { ...s.config, showGrid: show } })),

  setAmbientIntensity: (v) =>
    set((s) => ({ lightConfig: { ...s.lightConfig, ambientIntensity: clamp01(v) } })),
  setRimIntensity: (v) =>
    set((s) => ({ lightConfig: { ...s.lightConfig, rimLightIntensity: clamp01(v) } })),
  setSpotIntensity: (index, v) =>
    set((s) => ({
      lightConfig: {
        ...s.lightConfig,
        spotLights: s.lightConfig.spotLights.map((sp, i) =>
          i === index ? { ...sp, intensity: v } : sp
        )
      }
    })),
  setSpot: (index, partial) =>
    set((s) => ({
      lightConfig: {
        ...s.lightConfig,
        spotLights: s.lightConfig.spotLights.map((sp, i) =>
          i === index ? { ...sp, ...partial } : sp
        )
      }
    })),
  updateLightConfig: (partial) => set((s) => ({ lightConfig: { ...s.lightConfig, ...partial } })),

  loadFromProject: (data) =>
    set({
      config: { ...data.stage },
      lightConfig: {
        ...data.lighting,
        spotLights: data.lighting.spotLights.map((sp) => ({ ...sp }))
      }
    }),

  toJSON: () => ({ stage: { ...get().config }, lighting: structuredClone(get().lightConfig) })
}))

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}
function clamp01(v: number): number {
  return clamp(v, 0, 1)
}
