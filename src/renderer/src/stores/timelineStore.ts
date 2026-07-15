import { create } from 'zustand'
import { v4 as uuid } from 'uuid'
import type { TimelineTrack, TimelineClip, TimelineTrackType, ActiveClip } from '@shared/types/timeline'
import type { BeatMarker } from '@shared/types/motion'

interface TimelineStoreState {
  tracks: TimelineTrack[]
  duration: number
  audioPath: string | null
  audioDuration: number
  beatMarkers: BeatMarker[]

  addTrack: (type: TimelineTrackType, characterId?: string, label?: string) => string
  removeTrack: (trackId: string) => void
  reorderTracks: (from: number, to: number) => void
  toggleLock: (trackId: string) => void
  toggleMute: (trackId: string) => void

  addClip: (trackId: string, clip: Omit<TimelineClip, 'id'>) => string
  addClipFromMotion: (
    trackId: string,
    motionId: string,
    motionName: string,
    startTime: number,
    durationSec: number,
    frameCount: number,
    fps: number
  ) => string
  removeClip: (clipId: string) => void
  moveClip: (clipId: string, newStartTime: number, newTrackId?: string) => void
  trimClip: (clipId: string, trimStart: number, trimEnd: number) => void
  splitClip: (clipId: string, splitTime: number) => void

  setDuration: (d: number) => void
  setAudio: (path: string | null, duration?: number) => void
  setBeatMarkers: (m: BeatMarker[]) => void

  getClipsAtTime: (time: number) => ActiveClip[]
  /** Resolve the source-motion frame a clip is playing at project `time`. */
  getClipFrameAtTime: (clip: TimelineClip, time: number, fps: number) => number | null

  loadFromProject: (data: { duration: number; tracks: TimelineTrack[] }) => void
  toJSON: () => { duration: number; tracks: TimelineTrack[] }
}

const TRACK_COLORS: Record<TimelineTrackType, string> = {
  character: '#3b82f6',
  camera: '#eab308',
  vfx: '#a855f7'
}

export const useTimelineStore = create<TimelineStoreState>((set, get) => ({
  tracks: [],
  duration: 30,
  audioPath: null,
  audioDuration: 0,
  beatMarkers: [],

  addTrack: (type, characterId, label) => {
    const id = uuid()
    const track: TimelineTrack = {
      id,
      type,
      characterId,
      label: label ?? defaultTrackLabel(type, get().tracks.length),
      color: TRACK_COLORS[type],
      locked: false,
      muted: false,
      clips: []
    }
    set((s) => ({ tracks: [...s.tracks, track] }))
    return id
  },

  removeTrack: (trackId) =>
    set((s) => ({ tracks: s.tracks.filter((t) => t.id !== trackId) })),

  reorderTracks: (from, to) =>
    set((s) => {
      const tracks = [...s.tracks]
      const [moved] = tracks.splice(from, 1)
      tracks.splice(to, 0, moved)
      return { tracks }
    }),

  toggleLock: (trackId) =>
    set((s) => ({
      tracks: s.tracks.map((t) => (t.id === trackId ? { ...t, locked: !t.locked } : t))
    })),
  toggleMute: (trackId) =>
    set((s) => ({
      tracks: s.tracks.map((t) => (t.id === trackId ? { ...t, muted: !t.muted } : t))
    })),

  addClip: (trackId, clip) => {
    // Defensive: motion clips only belong on character tracks. The UI already
    // gates this (camera/vfx lanes reject the drop), but keep the store honest
    // so a future caller can't silently land a motion on the wrong track.
    const track = get().tracks.find((t) => t.id === trackId)
    if (!track || track.type !== 'character') {
      console.warn(`[timeline] addClip rejected: track ${trackId} is not a character track`)
      return ''
    }
    const id = uuid()
    const full: TimelineClip = { ...clip, id }
    set((s) => ({
      tracks: s.tracks.map((t) =>
        t.id === trackId ? { ...t, clips: [...t.clips, full] } : t
      ),
      duration: Math.max(s.duration, clip.startTime + clip.duration + 0.5)
    }))
    return id
  },

  addClipFromMotion: (trackId, motionId, motionName, startTime, durationSec, frameCount, fps) => {
    return get().addClip(trackId, {
      motionId,
      motionName,
      startTime,
      duration: durationSec,
      motionStartFrame: 0,
      motionEndFrame: Math.max(1, frameCount - 1),
      speed: 1,
      loop: false,
      color: '#475569'
    })
  },

  removeClip: (clipId) =>
    set((s) => ({
      tracks: s.tracks.map((t) => ({
        ...t,
        clips: t.clips.filter((c) => c.id !== clipId)
      }))
    })),

  moveClip: (clipId, newStartTime, newTrackId) =>
    set((s) => ({
      tracks: s.tracks.map((t) => {
        if (newTrackId && t.id !== newTrackId) {
          // remove from this track if it lived here
          return { ...t, clips: t.clips.filter((c) => c.id !== clipId) }
        }
        return {
          ...t,
          clips: t.clips.map((c) =>
            c.id === clipId ? { ...c, startTime: Math.max(0, newStartTime) } : c
          )
        }
      })
    })),

  trimClip: (clipId, trimStart, trimEnd) =>
    set((s) => ({
      tracks: s.tracks.map((t) => ({
        ...t,
        clips: t.clips.map((c) => {
          if (c.id !== clipId) return c
          const duration = Math.max(0.05, trimEnd - trimStart)
          return { ...c, startTime: trimStart, duration }
        })
      }))
    })),

  splitClip: (clipId, splitTime) =>
    set((s) => {
      const tracks = s.tracks.map((t) => {
        const clip = t.clips.find((c) => c.id === clipId)
        if (!clip) return t
        const localSplit = splitTime - clip.startTime
        if (localSplit <= 0.01 || localSplit >= clip.duration - 0.01) return t
        const first: TimelineClip = { ...clip, duration: localSplit }
        const second: TimelineClip = {
          ...clip,
          id: uuid(),
          startTime: splitTime,
          duration: clip.duration - localSplit
        }
        return { ...t, clips: [...t.clips.filter((c) => c.id !== clipId), first, second] }
      })
      return { tracks }
    }),

  setDuration: (d) => set({ duration: Math.max(1, d) }),

  setAudio: (path, duration) =>
    set({ audioPath: path, audioDuration: duration ?? get().audioDuration }),

  setBeatMarkers: (m) => set({ beatMarkers: m }),

  getClipsAtTime: (time) => {
    const out: ActiveClip[] = []
    for (const track of get().tracks) {
      if (track.muted) continue
      for (const clip of track.clips) {
        if (time >= clip.startTime && time < clip.startTime + clip.duration) {
          out.push({ trackId: track.id, clip })
        }
      }
    }
    return out
  },

  getClipFrameAtTime: (clip, time, fps) => {
    if (time < clip.startTime || time >= clip.startTime + clip.duration) return null
    const local = time - clip.startTime
    const frameRange = Math.max(1, clip.motionEndFrame - clip.motionStartFrame)
    const speed = clip.speed || 1
    let localFrame = (local * speed * fps) % frameRange
    if (!clip.loop && local * speed * fps >= frameRange) {
      localFrame = frameRange - 1
    }
    return clip.motionStartFrame + localFrame
  },

  loadFromProject: (data) =>
    set({ duration: data.duration, tracks: data.tracks.map((t) => ({ ...t })) }),

  toJSON: () => ({
    duration: get().duration,
    tracks: get().tracks.map((t) => ({ ...t, clips: t.clips.map((c) => ({ ...c })) }))
  })
}))

function defaultTrackLabel(type: TimelineTrackType, index: number): string {
  if (type === 'character') return `Character ${index + 1}`
  if (type === 'camera') return 'Camera'
  return 'VFX'
}
