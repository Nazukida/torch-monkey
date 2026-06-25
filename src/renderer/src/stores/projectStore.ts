import { create } from 'zustand'
import { v4 as uuid } from 'uuid'
import type { ProjectFile, ProjectMetadata } from '@shared/types/project'
import { PROJECT_FILE_VERSION } from '@shared/types/project'
import { DEFAULT_STAGE_CONFIG, DEFAULT_LIGHT_CONFIG } from '@shared/types/stage'
import { DEFAULT_VFX_CONFIG } from '@shared/types/vfx'
import { useStageStore } from './stageStore'
import { useCharacterStore } from './characterStore'
import { useTimelineStore } from './timelineStore'
import { useVfxStore } from './vfxStore'

interface ProjectState {
  metadata: ProjectMetadata
  currentPath: string | null
  dirty: boolean
  setDirty: (v: boolean) => void
  setName: (name: string) => void

  newProject: (name?: string) => void
  assemble: () => ProjectFile
  applyProject: (file: ProjectFile) => void

  save: () => Promise<{ path?: string; error?: string }>
  saveAs: () => Promise<{ path?: string; error?: string }>
  open: () => Promise<{ error?: string }>
  loadFromDb: (id: string) => Promise<{ error?: string }>
}

function defaultMetadata(name: string): ProjectMetadata {
  const now = new Date().toISOString()
  return {
    name,
    created: now,
    updated: now,
    author: 'nazuki',
    description: ''
  }
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  metadata: defaultMetadata('Untitled Project'),
  currentPath: null,
  dirty: false,
  setDirty: (v) => set({ dirty: v }),
  setName: (name) =>
    set((s) => ({ metadata: { ...s.metadata, name, updated: new Date().toISOString() }, dirty: true })),

  newProject: (name) => {
    useStageStore.getState().loadFromProject({
      stage: { ...DEFAULT_STAGE_CONFIG },
      lighting: {
        ...DEFAULT_LIGHT_CONFIG,
        spotLights: DEFAULT_LIGHT_CONFIG.spotLights.map((s) => ({ ...s }))
      }
    })
    for (const id of Array.from(useCharacterStore.getState().models.keys())) {
      useCharacterStore.getState().removeCharacter(id)
    }
    useCharacterStore.getState().loadFromProject([])
    useTimelineStore.getState().loadFromProject({ duration: 30, tracks: [] })
    useVfxStore.getState().loadFromProject(structuredClone(DEFAULT_VFX_CONFIG))
    set({ metadata: defaultMetadata(name ?? 'Untitled Project'), currentPath: null, dirty: false })
  },

  assemble: () => {
    const stage = useStageStore.getState().toJSON()
    const characters = useCharacterStore.getState().toJSON()
    const timeline = useTimelineStore.getState().toJSON()
    const vfx = useVfxStore.getState().toJSON()
    const motionRefs = new Set<string>()
    for (const t of timeline.tracks) for (const c of t.clips) motionRefs.add(c.motionId)

    const file: ProjectFile = {
      version: PROJECT_FILE_VERSION,
      metadata: { ...get().metadata, updated: new Date().toISOString() },
      stage: stage.stage,
      lighting: stage.lighting,
      characters,
      timeline,
      vfx,
      motionRefs: Array.from(motionRefs)
    }
    return file
  },

  applyProject: (file) => {
    useStageStore.getState().loadFromProject({ stage: file.stage, lighting: file.lighting })
    useCharacterStore.getState().loadFromProject(file.characters)
    useTimelineStore.getState().loadFromProject(file.timeline)
    useVfxStore.getState().loadFromProject(file.vfx)
    if (file.audioPath) useTimelineStore.getState().setAudio(file.audioPath)
    set({ metadata: file.metadata, dirty: false })
  },

  save: async () => {
    const file = get().assemble()
    file.metadata = { ...file.metadata, updated: new Date().toISOString() }
    // Mirror into the DB (recent projects / autosave). The DB handler derives
    // the project id from metadata.name when none is present.
    await window.electronAPI.dbSaveProject(file)
    if (get().currentPath) {
      const res = await window.electronAPI.projectSaveAs(file)
      if (res.error) return { error: res.error }
      set({ dirty: false, currentPath: res.path ?? get().currentPath, metadata: file.metadata })
      return { path: get().currentPath ?? undefined }
    }
    return get().saveAs()
  },

  saveAs: async () => {
    const file = get().assemble()
    file.metadata = { ...file.metadata, updated: new Date().toISOString() }
    const res = await window.electronAPI.projectSaveAs(file)
    if (res.error) return { error: res.error }
    set({ dirty: false, currentPath: res.path ?? null, metadata: file.metadata })
    return { path: res.path }
  },

  open: async () => {
    const res = await window.electronAPI.projectOpen()
    if (res.error || !res.data) return { error: res.error ?? 'No file' }
    get().applyProject(res.data)
    set({ currentPath: res.path ?? null, dirty: false })
    return {}
  },

  loadFromDb: async (id) => {
    const file = await window.electronAPI.dbGetProject(id)
    if (!file) return { error: 'Project not found' }
    get().applyProject(file)
    set({ currentPath: null, dirty: false })
    return {}
  }
}))
