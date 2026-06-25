/**
 * Character configuration types.
 * A character = an appearance + a stage placement. Skeleton animation data is
 * shared and lives in {@link motion.ts} (referenced by motionId), decoupled per
 * the MMD-style model/motion/camera/vfx separation.
 */

export type ModelSource = 'default' | 'procedural' | 'custom'

export interface CharacterConfig {
  id: string
  /** Display name, e.g. "Player 1". */
  name: string

  // ---- Appearance ----
  modelSource: ModelSource
  /** Absolute or project-relative path to a custom .glb. */
  customModelPath?: string
  /** Custom-model bone name -> standard SkeletonJoint name. */
  skeletonMapping?: Record<string, string>

  // ---- Body (does not affect motion data, only the visual rig) ----
  /** Height in meters. Default 1.7, range 1.0–2.5. */
  height: number
  /** Overall scale factor derived from height. */
  bodyScale: number

  // ---- Stage placement ----
  /** World position [x, y, z]. */
  position: [number, number, number]
  /** Y-axis rotation in degrees. */
  rotation: number

  // ---- Display ----
  visible: boolean
  /** Developer mode: visualize the skeleton bones. */
  showSkeleton: boolean
  /** 0–1 opacity. */
  opacity: number

  // ---- Tint (simple color override for procedural models) ----
  color: string
}

/** A minimal metadata record used by the character list panel. */
export interface CharacterMeta {
  id: string
  name: string
  visible: boolean
}

export const DEFAULT_CHARACTER_CONFIG = (id: string): Omit<CharacterConfig, 'id'> => ({
  name: 'Player',
  modelSource: 'procedural',
  height: 1.7,
  bodyScale: 1.0,
  position: [0, 0, 0],
  rotation: 0,
  visible: true,
  showSkeleton: false,
  opacity: 1.0,
  color: '#9fb4d4'
})
