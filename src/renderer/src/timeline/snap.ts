import type { TimelineClip } from '@shared/types/timeline'

/**
 * Magnetic-snap helper for the timeline. Snap targets are the timeline origin
 * (0), the playhead, and — for every OTHER clip — both its start and its end
 * edge. A candidate time within `threshold` seconds of a target is rounded onto
 * it, so clips can be butted gap-free against neighbours, the playhead, or the
 * start. The threshold is in SECONDS so snap feel is identical at any zoom (pps).
 *
 * Pure & allocation-light: the caller gathers the clip list once per drag move.
 */
export interface SnapContext {
  /** Id of the clip being dragged (excluded so a clip can't snap to its own edges). */
  activeClipId: string
  clips: TimelineClip[]
  playhead: number
  origin: number
  threshold: number
}

export interface SnapResult {
  /** The (possibly snapped) time. */
  time: number
  /** The target the time snapped to, or null if no target was in range. */
  matchedTarget: number | null
}

export function snapTime(t: number, ctx: SnapContext): SnapResult {
  if (ctx.threshold <= 0) return { time: t, matchedTarget: null }

  const targets: number[] = [ctx.origin, ctx.playhead]
  for (const c of ctx.clips) {
    if (c.id === ctx.activeClipId) continue // never snap to self
    targets.push(c.startTime, c.startTime + c.duration)
  }

  let best = t
  let bestDist = ctx.threshold
  let matched: number | null = null
  for (const tgt of targets) {
    const d = Math.abs(t - tgt)
    // `<=` so a target sitting exactly at the threshold still wins.
    if (d <= bestDist) {
      bestDist = d
      best = tgt
      matched = tgt
    }
  }
  return { time: best, matchedTarget: matched }
}
