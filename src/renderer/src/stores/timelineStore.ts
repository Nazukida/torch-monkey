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

  /** Magnetic snap while dragging/dropping clips (gap-free placement). */
  snapEnabled: boolean
  snapThreshold: number
  toggleSnap: () => void
  setSnapThreshold: (v: number) => void

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

/**
 * A character track is *monophonic*: the performer can only hold one pose at a
 * given instant, so two clips must never cover the same moment. If they do, the
 * scene controller ends up calling `seekToFrame` twice for one player in one
 * frame and the winner is decided by array order (which `splitClip` reorders),
 * i.e. the pose shown is arbitrary.
 *
 * Returns the legal start time closest to `desired` at which a clip of
 * `duration` fits between `others` without overlapping any of them.
 */
const EPS = 1e-6

/**
 * Clips are kept sorted by `startTime` after every mutation. Nothing should
 * depend on their array order — but `splitClip` used to append the two halves
 * at the end, silently reshuffling the lane. Normalising here means the order
 * is always the order you see on screen.
 */
function sortClips(clips: TimelineClip[]): TimelineClip[] {
  return [...clips].sort((a, b) => a.startTime - b.startTime)
}

function nearestFreeStart(
  others: TimelineClip[],
  desired: number,
  duration: number
): number {
  const sorted = [...others].sort((a, b) => a.startTime - b.startTime)
  const gaps: Array<[number, number]> = []
  let cursor = 0
  for (const c of sorted) {
    if (c.startTime - cursor >= duration - EPS) gaps.push([cursor, c.startTime - duration])
    cursor = Math.max(cursor, c.startTime + c.duration)
  }
  gaps.push([cursor, Number.POSITIVE_INFINITY])

  const want = Math.max(0, desired)
  let best = cursor
  let bestDist = Number.POSITIVE_INFINITY
  for (const [lo, hi] of gaps) {
    const cand = Math.min(Math.max(want, lo), hi)
    const dist = Math.abs(cand - want)
    if (dist < bestDist) {
      bestDist = dist
      best = cand
    }
  }
  return Math.max(0, best)
}

export const useTimelineStore = create<TimelineStoreState>((set, get) => ({
  tracks: [],
  duration: 30,
  audioPath: null,
  audioDuration: 0,
  beatMarkers: [],

  snapEnabled: true,
  snapThreshold: 0.08,
  toggleSnap: () => set((s) => ({ snapEnabled: !s.snapEnabled })),
  setSnapThreshold: (v) => set({ snapThreshold: Math.max(0, v) }),

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
    // Never drop a clip on top of one that is already there.
    const startTime = nearestFreeStart(track.clips, clip.startTime, clip.duration)
    const full: TimelineClip = { ...clip, id, startTime }
    set((s) => ({
      tracks: s.tracks.map((t) =>
        t.id === trackId ? { ...t, clips: sortClips([...t.clips, full]) } : t
      ),
      duration: Math.max(s.duration, startTime + clip.duration + 0.5)
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
    set((s) => {
      const moving = s.tracks.flatMap((t) => t.clips).find((c) => c.id === clipId)
      if (!moving) return {}
      const targetId = newTrackId ?? s.tracks.find((t) => t.clips.some((c) => c.id === clipId))?.id
      const target = s.tracks.find((t) => t.id === targetId)
      // Clamp against every clip on the destination track except the one moving.
      const start = nearestFreeStart(
        (target?.clips ?? []).filter((c) => c.id !== clipId),
        newStartTime,
        moving.duration
      )
      return {
        tracks: s.tracks.map((t) => {
          if (t.id !== targetId) {
            // Dragged to another lane: drop it from the one it used to live on.
            return t.clips.some((c) => c.id === clipId)
              ? { ...t, clips: t.clips.filter((c) => c.id !== clipId) }
              : t
          }
          const already = t.clips.some((c) => c.id === clipId)
          const clips = already
            ? t.clips.map((c) => (c.id === clipId ? { ...c, startTime: start } : c))
            : [...t.clips, { ...moving, startTime: start }]
          return { ...t, clips: sortClips(clips) }
        })
      }
    }),

  trimClip: (clipId, trimStart, trimEnd) =>
    set((s) => ({
      tracks: s.tracks.map((t) => {
        if (!t.clips.some((c) => c.id === clipId)) return t
        const others = t.clips.filter((c) => c.id !== clipId)
        // A resize must stop at the neighbours' edges, not run through them.
        const leftBound = Math.max(
          0,
          ...others.map((o) => o.startTime + o.duration).filter((e) => e <= trimEnd + EPS)
        )
        const rightCandidates = others
          .map((o) => o.startTime)
          .filter((st) => st >= trimStart - EPS)
        const rightBound = rightCandidates.length
          ? Math.min(...rightCandidates)
          : Number.POSITIVE_INFINITY
        const start = Math.max(trimStart, leftBound)
        const end = Math.min(trimEnd, rightBound)
        return {
          ...t,
          clips: sortClips(
            t.clips.map((c) =>
              c.id === clipId
                ? { ...c, startTime: start, duration: Math.max(0.05, end - start) }
                : c
            )
          )
        }
      })
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
        return {
          ...t,
          clips: sortClips([...t.clips.filter((c) => c.id !== clipId), first, second])
        }
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
