import { usePlaybackStore } from '@renderer/stores/playbackStore'
import { useTimelineStore } from '@renderer/stores/timelineStore'

/**
 * Global keyboard shortcuts. Returns a disposer.
 *  - Space / K          play / pause
 *  - Home / End         jump to start / end
 *  - Left / Right       step one frame
 *  - L                  toggle loop of focused clip (no-op stub)
 */
export function bindKeyboardShortcuts(): () => void {
  const handler = (e: KeyboardEvent): void => {
    const target = e.target as HTMLElement | null
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
      return
    }

    const timeline = useTimelineStore.getState()
    const duration = timeline.duration
    const playback = usePlaybackStore.getState()

    switch (e.code) {
      case 'Space':
      case 'KeyK':
        e.preventDefault()
        if (playback.status === 'playing') playback.pause()
        else playback.play(duration)
        break
      case 'Home':
        e.preventDefault()
        playback.seek(0, duration)
        break
      case 'End':
        e.preventDefault()
        playback.seek(duration, duration)
        break
      case 'ArrowLeft':
        e.preventDefault()
        playback.seek(Math.max(0, playback.currentTime - 1 / 30), duration)
        break
      case 'ArrowRight':
        e.preventDefault()
        playback.seek(Math.min(duration, playback.currentTime + 1 / 30), duration)
        break
    }
  }

  window.addEventListener('keydown', handler)
  return () => window.removeEventListener('keydown', handler)
}
