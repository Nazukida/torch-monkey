import { Quaternion } from '@babylonjs/core'
import { SkeletonJoint } from '@shared/constants/skeleton'
import { BabylonEngine } from '@renderer/engine/BabylonEngine'
import type { CharacterModel } from './CharacterModel'
import type { MotionData, FramePose, JointTransform } from '@shared/types/motion'
import { clampPose } from './jointLimits'

/**
 * Drives a {@link CharacterModel} from a {@link MotionData}.
 *
 * Two usage modes:
 *  - Timeline-driven: the playback engine computes a fractional frame and calls
 *    {@link seekToFrame} each tick.
 *  - Standalone preview: {@link play} advances internal time via the engine's
 *    per-frame callback (used by the motion-library preview viewport).
 *
 * Root-trajectory rebasing: the pelvis world position from capture is stored
 * relative to its first frame, so the character starts at its stage placement
 * and locomotion is applied as a delta.
 */
export class MotionPlayer {
  private model: CharacterModel
  private motion: MotionData | null = null
  private rootOrigin: [number, number, number] | undefined = undefined

  private currentTime = 0 // seconds
  private speed = 1
  private loop = false
  private playing = false
  private disposeEngineCb: (() => void) | null = null
  /**
   * When true (default), every applied pose is clamped to anatomical joint limits
   * so no motion can drive a limb into an impossible/穿模 pose (arm-crossing,
   * elbow lock-back, …). Disable for raw capture review.
   */
  enableJointLimits = true

  constructor(model: CharacterModel) {
    this.model = model
  }

  loadMotion(data: MotionData): void {
    this.motion = data
    const first = data.poses[0]?.transforms[SkeletonJoint.PELVIS]?.position
    this.rootOrigin = first ? ([first[0], first[1], first[2]] as [number, number, number]) : undefined
    this.currentTime = 0
    this.seekToFrame(0)
  }

  getMotion(): MotionData | null {
    return this.motion
  }

  hasMotion(): boolean {
    return this.motion !== null
  }

  play(): void {
    if (!this.motion || this.playing) return
    this.playing = true
    if (!this.disposeEngineCb) {
      this.disposeEngineCb = BabylonEngine.registerBeforeUpdate((delta) => {
        if (!this.playing) return
        this.advance(delta * this.speed)
      })
    }
  }

  pause(): void {
    this.playing = false
  }

  stop(): void {
    this.playing = false
    this.currentTime = 0
    this.seekToFrame(0)
  }

  seek(time: number): void {
    this.currentTime = Math.max(0, time)
    if (this.motion) this.applyAtTime(this.currentTime)
  }

  setSpeed(speed: number): void {
    this.speed = speed
  }

  setLoop(loop: boolean): void {
    this.loop = loop
  }

  get isPlaying(): boolean {
    return this.playing
  }

  get currentTimeSec(): number {
    return this.currentTime
  }

  /** Advance internal time (clamped/looped to motion duration). */
  private advance(delta: number): void {
    if (!this.motion) return
    this.currentTime += delta
    const duration = this.motion.duration
    if (this.currentTime >= duration) {
      if (this.loop) {
        this.currentTime = this.currentTime % Math.max(duration, 1e-6)
      } else {
        this.currentTime = duration
        this.playing = false
      }
    }
    this.applyAtTime(this.currentTime)
  }

  private applyAtTime(time: number): void {
    if (!this.motion) return
    const fps = this.motion.fps || 30
    const frameFloat = time * fps
    this.seekToFrame(frameFloat)
  }

  /**
   * Apply the interpolated pose at a fractional frame index. Public so the
   * timeline playback engine can drive it directly.
   */
  seekToFrame(frameFloat: number): void {
    if (!this.motion || this.motion.poses.length === 0) return
    const last = this.motion.frameCount - 1
    const f = Math.max(0, Math.min(frameFloat, last))
    const i0 = Math.floor(f)
    const i1 = Math.min(i0 + 1, last)
    const frac = f - i0
    const raw = this.interpolate(this.motion.poses[i0], this.motion.poses[i1], frac)
    const pose = this.enableJointLimits ? clampPose(raw) : raw
    this.model.applyPose(pose, this.rootOrigin)
  }

  private interpolate(prev: FramePose, next: FramePose, t: number): FramePose {
    const transforms: Record<number, JointTransform> = {}
    const keys = new Set<number>([
      ...Object.keys(prev.transforms).map(Number),
      ...Object.keys(next.transforms).map(Number)
    ])

    for (const idx of keys) {
      const a = prev.transforms[idx]
      const b = next.transforms[idx]
      if (!a && b) {
        transforms[idx] = b
        continue
      }
      if (a && !b) {
        transforms[idx] = a
        continue
      }
      if (!a || !b) continue

      const qa = new Quaternion(...a.rotation)
      const qb = new Quaternion(...b.rotation)
      const qr = Quaternion.Slerp(qa, qb, t)

      const out: JointTransform = { rotation: [qr.x, qr.y, qr.z, qr.w] }

      if (idx === SkeletonJoint.PELVIS && a.position && b.position) {
        out.position = [
          a.position[0] + (b.position[0] - a.position[0]) * t,
          a.position[1] + (b.position[1] - a.position[1]) * t,
          a.position[2] + (b.position[2] - a.position[2]) * t
        ]
      } else if (idx === SkeletonJoint.PELVIS && a.position) {
        out.position = a.position
      }
      transforms[idx] = out
    }
    return { frame: prev.frame, transforms }
  }

  dispose(): void {
    this.disposeEngineCb?.()
    this.disposeEngineCb = null
    this.playing = false
    this.motion = null
  }
}
