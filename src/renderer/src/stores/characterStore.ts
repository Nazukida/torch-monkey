import { create } from 'zustand'
import { v4 as uuid } from 'uuid'
import { Scene, ShadowGenerator } from '@babylonjs/core'
import { CharacterModel } from '@renderer/character/CharacterModel'
import { MotionPlayer } from '@renderer/character/MotionPlayer'
import { GlowstickVFX } from '@renderer/vfx/GlowstickVFX'
import { REFERENCE_REST_HEIGHT } from '@shared/constants/skeleton'
import type { CharacterConfig } from '@shared/types/character'
import { DEFAULT_CHARACTER_CONFIG } from '@shared/types/character'
import type { GlowstickConfig } from '@shared/types/vfx'
import { useVfxStore } from '@renderer/stores/vfxStore'

interface CharacterState {
  configs: Record<string, CharacterConfig>
  /** Live Babylon objects (non-serialized). */
  models: Map<string, CharacterModel>
  players: Map<string, MotionPlayer>
  selectedId: string | null

  /** Wired up by the viewport once the scene exists. */
  _scene: Scene | null
  _shadows: ShadowGenerator | null
  _vfx: GlowstickVFX | null
  init: (scene: Scene, shadows: ShadowGenerator | null, vfx: GlowstickVFX | null) => void
  reconcile: () => void

  addCharacter: (config?: Partial<CharacterConfig>) => string
  removeCharacter: (id: string) => void
  selectCharacter: (id: string | null) => void
  updateConfig: (id: string, partial: Partial<CharacterConfig>) => void
  duplicateCharacter: (id: string) => string | null
  alignCharacters: (mode: 'row' | 'v-formation') => void

  getModel: (id: string) => CharacterModel | undefined
  getPlayer: (id: string) => MotionPlayer | undefined
  list: () => CharacterConfig[]

  loadFromProject: (configs: CharacterConfig[]) => void
  toJSON: () => CharacterConfig[]
}

export const useCharacterStore = create<CharacterState>((set, get) => ({
  configs: {},
  models: new Map(),
  players: new Map(),
  selectedId: null,
  _scene: null,
  _shadows: null,
  _vfx: null,

  init: (scene, shadows, vfx) => set({ _scene: scene, _shadows: shadows, _vfx: vfx }),

  /** Build live models for any config that lacks one (e.g. created pre-scene). */
  reconcile: () => {
    const s = get()
    const scene = s._scene
    if (!scene) return
    for (const id of Object.keys(s.configs)) {
      if (s.models.has(id)) continue
      const cfg = { ...s.configs[id], bodyScale: s.configs[id].height / REFERENCE_REST_HEIGHT }
      const model = CharacterModel.createProcedural(id, cfg, scene)
      model.registerShadows(s._shadows)
      s._vfx?.createForCharacter(id, model, liveGlowConfig())
      const player = new MotionPlayer(model)
      s.models.set(id, model)
      s.players.set(id, player)
    }
  },

  addCharacter: (partial = {}) => {
    const id = uuid()
    const base = DEFAULT_CHARACTER_CONFIG(id)
    const cfg: CharacterConfig = {
      ...base,
      name: partial.name ?? nextDefaultName(get().configs),
      ...partial,
      id,
      position: partial.position ?? nextFreePosition(get().configs)
    }
    // Derive bodyScale from height so the rig matches the requested stature.
    cfg.bodyScale = cfg.height / REFERENCE_REST_HEIGHT

    const scene = get()._scene
    if (scene) {
      const model = CharacterModel.createProcedural(id, cfg, scene)
      model.registerShadows(get()._shadows)
      get()._vfx?.createForCharacter(id, model, liveGlowConfig())
      const player = new MotionPlayer(model)

      set((s) => ({
        configs: { ...s.configs, [id]: cfg },
        models: new Map(s.models).set(id, model),
        players: new Map(s.players).set(id, player),
        selectedId: s.selectedId ?? id
      }))
    } else {
      set((s) => ({ configs: { ...s.configs, [id]: cfg }, selectedId: s.selectedId ?? id }))
    }
    return id
  },

  removeCharacter: (id) =>
    set((s) => {
      const models = new Map(s.models)
      const players = new Map(s.players)
      players.get(id)?.dispose()
      get()._vfx?.removeCharacter(id)
      models.get(id)?.dispose()
      models.delete(id)
      players.delete(id)
      const configs = { ...s.configs }
      delete configs[id]
      return {
        configs,
        models,
        players,
        selectedId: s.selectedId === id ? null : s.selectedId
      }
    }),

  selectCharacter: (id) => set({ selectedId: id }),

  updateConfig: (id, partial) =>
    set((s) => {
      const cfg = s.configs[id]
      if (!cfg) return {}
      const next: CharacterConfig = { ...cfg, ...partial, id }
      if (partial.height !== undefined) next.bodyScale = next.height / REFERENCE_REST_HEIGHT

      const model = s.models.get(id)
      if (model) {
        if (partial.bodyScale !== undefined) model.applyScale(partial.bodyScale)
        if (partial.height !== undefined) model.applyScale(next.bodyScale)
        if (partial.color !== undefined) model.setColor(partial.color)
        if (partial.opacity !== undefined) model.setOpacity(partial.opacity)
        if (partial.visible !== undefined) model.setVisible(partial.visible)
        if (partial.showSkeleton !== undefined && get()._scene)
          model.setShowSkeleton(partial.showSkeleton, get()._scene as Scene)
        if (partial.position !== undefined) model.setPosition(...partial.position)
        if (partial.rotation !== undefined) model.setRotationDeg(partial.rotation)
      }
      return { configs: { ...s.configs, [id]: next } }
    }),

  duplicateCharacter: (id) => {
    const cfg = get().configs[id]
    if (!cfg) return null
    const newId = get().addCharacter({
      ...cfg,
      name: `${cfg.name} copy`,
      position: [cfg.position[0] + 1.5, cfg.position[1], cfg.position[2]]
    })
    return newId
  },

  alignCharacters: (mode) =>
    set((s) => {
      const ids = Object.keys(s.configs)
      const configs = { ...s.configs }
      ids.forEach((id, i) => {
        let pos: [number, number, number]
        if (mode === 'row') {
          const n = ids.length
          pos = [(i - (n - 1) / 2) * 1.8, 0, 0]
        } else {
          // v-formation
          const row = Math.floor(i / 2)
          const side = i % 2 === 0 ? -1 : 1
          pos = [side * (row + 1) * 0.9, 0, -row * 1.2]
        }
        configs[id] = { ...configs[id], position: pos }
        s.models.get(id)?.setPosition(pos[0], pos[1], pos[2])
      })
      return { configs }
    }),

  getModel: (id) => get().models.get(id),
  getPlayer: (id) => get().players.get(id),
  list: () => Object.values(get().configs),

  loadFromProject: (configs) => {
    // Dispose existing live models first.
    for (const id of Array.from(get().models.keys())) get().removeCharacter(id)
    const scene = get()._scene
    const map: Record<string, CharacterConfig> = {}
    for (const cfg of configs) {
      map[cfg.id] = { ...cfg, bodyScale: cfg.height / REFERENCE_REST_HEIGHT }
      if (scene) {
        const model = CharacterModel.createProcedural(cfg.id, map[cfg.id], scene)
        model.registerShadows(get()._shadows)
        get()._vfx?.createForCharacter(cfg.id, model, liveGlowConfig())
        const player = new MotionPlayer(model)
        get().players.set(cfg.id, player)
        get().models.set(cfg.id, model)
      }
    }
    set({ configs: map, selectedId: configs[0]?.id ?? null })
  },

  toJSON: () => Object.values(get().configs).map((c) => ({ ...c }))
}))

function nextDefaultName(configs: Record<string, CharacterConfig>): string {
  const n = Object.keys(configs).length + 1
  return `Player ${n}`
}

function nextFreePosition(configs: Record<string, CharacterConfig>): [number, number, number] {
  const n = Object.keys(configs).length
  return [(n - (n % 2 === 0 ? n / 2 : (n - 1) / 2)) * 1.8, 0, 0]
}

/** The current glowstick config from the VFX store, so freshly-added (and
 *  project-loaded) characters pick up the user's panel settings instead of a
 *  hardcoded default. Live edits thereafter flow through SceneController. */
function liveGlowConfig(): GlowstickConfig {
  return useVfxStore.getState().config.glowstick
}
