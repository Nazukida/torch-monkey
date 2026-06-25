import { create } from 'zustand'

interface PlaybackState {
  status: 'stopped' | 'playing' | 'paused'
  currentTime: number // seconds
  speed: number

  audioBuffer: AudioBuffer | null
  audioName: string | null

  play: (totalDuration: number) => void
  pause: () => void
  stop: () => void
  seek: (time: number, totalDuration: number) => void
  setSpeed: (v: number) => void
  tick: (delta: number, totalDuration: number) => void

  loadAudio: (buffer: AudioBuffer, name: string) => void
  clearAudio: () => void
}

// Lazily-created shared AudioContext (created on first play to satisfy
// browser autoplay policies).
let sharedCtx: AudioContext | null = null
function getAudioCtx(): AudioContext | null {
  if (typeof window === 'undefined') return null
  if (!sharedCtx) {
    const Ctor: typeof AudioContext =
      (window as unknown as { AudioContext: typeof AudioContext }).AudioContext
    if (!Ctor) return null
    sharedCtx = new Ctor()
  }
  return sharedCtx
}

export const usePlaybackStore = create<PlaybackState>((set, get) => {
  let sourceNode: AudioBufferSourceNode | null = null
  let audioStartCtxTime = 0
  let audioStartOffset = 0

  function stopSource(): void {
    try {
      sourceNode?.stop()
    } catch {
      /* already stopped */
    }
    sourceNode = null
  }

  function startSource(offset: number, rate: number): void {
    const ctx = getAudioCtx()
    const buffer = get().audioBuffer
    if (!ctx || !buffer) return
    stopSource()
    sourceNode = ctx.createBufferSource()
    sourceNode.buffer = buffer
    sourceNode.playbackRate.value = rate
    sourceNode.connect(ctx.destination)
    sourceNode.start(0, Math.max(0, Math.min(offset, buffer.duration)))
    audioStartCtxTime = ctx.currentTime
    audioStartOffset = offset
  }

  return {
    status: 'stopped',
    currentTime: 0,
    speed: 1,
    audioBuffer: null,
    audioName: null,

    play: (totalDuration) => {
      const ctx = getAudioCtx()
      ctx?.resume?.()
      if (get().status !== 'playing' && get().audioBuffer) {
        startSource(get().currentTime, get().speed)
      }
      set({ status: 'playing' })
    },

    pause: () => {
      if (get().audioBuffer) {
        // Sample current audio position before stopping.
        const ctx = getAudioCtx()
        if (ctx && sourceNode) {
          const elapsed = (ctx.currentTime - audioStartCtxTime) * get().speed
          set({ currentTime: audioStartOffset + elapsed })
        }
        stopSource()
      }
      set({ status: 'paused' })
    },

    stop: () => {
      stopSource()
      set({ status: 'stopped', currentTime: 0 })
    },

    seek: (time, _totalDuration) => {
      const clamped = Math.max(0, time)
      set({ currentTime: clamped })
      if (get().status === 'playing' && get().audioBuffer) {
        startSource(clamped, get().speed)
      }
    },

    setSpeed: (v) => {
      set({ speed: v })
      if (get().status === 'playing' && sourceNode) {
        sourceNode.playbackRate.value = v
      }
    },

    tick: (delta, totalDuration) => {
      if (get().status !== 'playing') return
      const next = get().currentTime + delta * get().speed
      if (next >= totalDuration) {
        stopSource()
        set({ currentTime: totalDuration, status: 'stopped' })
        return
      }
      set({ currentTime: next })
    },

    loadAudio: (buffer, name) => {
      stopSource()
      set({ audioBuffer: buffer, audioName: name, currentTime: 0, status: 'stopped' })
    },

    clearAudio: () => {
      stopSource()
      set({ audioBuffer: null, audioName: null })
    }
  }
})
