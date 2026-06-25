/**
 * Internal motion data model.
 *
 * The on-disk format mirrors exactly the JSON produced by the Python
 * `pipeline/format_exporter.py` (camelCase keys). Rotations are per-joint LOCAL
 * quaternions (relative to the parent bone); only the root joint (PELVIS, index 0)
 * carries a world-space `position`.
 */

/** Local rotation as a quaternion [x, y, z, w]. */
export type Quat = [number, number, number, number]

/** Local translation [x, y, z] (root joint only). */
export type Vec3 = [number, number, number]

/** A single joint's transform within a frame. */
export interface JointTransform {
  rotation: Quat
  /** Only present on the root joint (PELVIS). */
  position?: Vec3
}

/** A single frame's full pose: joint index -> transform. */
export interface FramePose {
  frame: number
  transforms: Record<number, JointTransform>
  /** 0–1 mean confidence of the underlying capture at this frame. */
  confidence?: number
}

export type BeatType = 'kime' | 'downbeat' | 'transition' | 'custom'

export interface BeatMarker {
  frame: number
  /** Music-beat label, e.g. "1-1-1", or '' when no music. */
  beat: string
  type: BeatType
  label?: string
}

/** The canonical, complete motion record. */
export interface MotionData {
  id: string
  name: string
  description?: string
  tags: string[]

  fps: number
  duration: number
  frameCount: number
  skeletonType: 'smpl_24'

  poses: FramePose[]
  beatMarkers: BeatMarker[]
  keyframeFlags: number[]

  motionIntensity: number
  primaryJoints: number[]
  isLoopable: boolean

  source: 'ai-capture' | 'manual' | 'imported'
  sourceVideoPath?: string
  /** Base64 PNG thumbnail for the library preview. */
  thumbnail?: string
  createdAt: string
  updatedAt: string
}

/** A reference to a motion on the timeline. */
export interface MotionClip {
  id: string
  motionId: string
  /** Redundant motion name for fast display without a lookup. */
  motionName: string
  /** Start frame into the source motion. */
  startFrame: number
  /** End frame into the source motion. */
  endFrame: number
  /** Playback speed multiplier (1 = original). */
  speed: number
  loop: boolean
}

/** Lightweight list metadata (no `poses`, for the motion library panel). */
export interface MotionMeta {
  id: string
  name: string
  description?: string
  duration: number
  fps: number
  frameCount: number
  tags: string[]
  motionIntensity: number
  source: MotionData['source']
  thumbnail?: string
  updatedAt: string
}

/** Options for `db:listMotions`. */
export interface ListMotionsOptions {
  search?: string
  tags?: string[]
  source?: string
  sortBy?: 'name' | 'created_at' | 'intensity' | 'updated_at'
  sortOrder?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

export interface ListMotionsResult {
  motions: MotionMeta[]
  total: number
}
