/**
 * Project file format (.tmonkey = JSON + resource references).
 * Composes the four decoupled layers: model(staged via characters) / motion /
 * camera(timeline camera track) / vfx.
 */
import type { StageConfig, LightConfig } from './stage'
import type { CharacterConfig } from './character'
import type { TimelineTrack } from './timeline'
import type { VFXConfig } from './vfx'

export interface ProjectMetadata {
  name: string
  created: string
  updated: string
  author: string
  description?: string
}

export interface ProjectTimelineData {
  duration: number
  tracks: TimelineTrack[]
}

export interface ProjectFile {
  version: string
  metadata: ProjectMetadata

  stage: StageConfig
  lighting: LightConfig

  characters: CharacterConfig[]

  timeline: ProjectTimelineData

  vfx: VFXConfig

  /** Project-relative audio path. */
  audioPath?: string

  /** motionIds used by the timeline (resolved against the SQLite motion store). */
  motionRefs: string[]
}

export const PROJECT_FILE_VERSION = '1.0.0'

/** Lightweight project record for the "recent projects" list. */
export interface ProjectListItem {
  id: string
  name: string
  thumbnail?: string
  updatedAt: string
}
