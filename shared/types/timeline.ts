/**
 * Timeline data model. Clips live on tracks; tracks are typed by what they drive.
 */
import type { BeatMarker } from './motion'

export type TimelineTrackType = 'character' | 'camera' | 'vfx'

export interface TimelineClip {
  id: string
  motionId: string
  motionName: string

  /** Position on the timeline, in seconds. */
  startTime: number
  /** Duration on the timeline, in seconds. */
  duration: number

  /** Source-motion frame window actually played. */
  motionStartFrame: number
  motionEndFrame: number

  /** Playback speed (1 = original). */
  speed: number
  loop: boolean

  /** Hex color. */
  color: string
}

export interface TimelineTrack {
  id: string
  type: TimelineTrackType
  /** Only for 'character' tracks. */
  characterId?: string
  label: string
  color: string
  locked: boolean
  /** Skip this track during playback (mute a character / hide vfx). */
  muted: boolean
  clips: TimelineClip[]
}

export interface TimelineState {
  tracks: TimelineTrack[]
  /** Total project duration in seconds. */
  duration: number

  audioPath: string | null
  audioDuration: number
  /** Global (music) beat markers, separate from per-motion kime markers. */
  beatMarkers: BeatMarker[]
}

export interface ActiveClip {
  trackId: string
  clip: TimelineClip
}
