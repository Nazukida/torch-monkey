import { v4 as uuid } from 'uuid'
import { Quaternion, Vector3 } from '@babylonjs/core'
import { SkeletonJoint } from '@shared/constants/skeleton'
import { useMotionStore } from '@renderer/stores/motionStore'
import { SMPL24_REST_POSE } from '@shared/constants/skeleton'
import type { MotionData, FramePose, JointTransform, BeatMarker } from '@shared/types/motion'

/** Axis-angle quaternion as [x,y,z,w]. */
function qAxis(axis: [number, number, number], angle: number): [number, number, number, number] {
  const a = Quaternion.RotationAxis(new Vector3(axis[0], axis[1], axis[2]).normalize(), angle)
  return [a.x, a.y, a.z, a.w]
}
function qIdentity(): [number, number, number, number] {
  return [0, 0, 0, 1]
}

interface MotionSpec {
  name: string
  description: string
  tags: string[]
  fps: number
  duration: number
  /** Given frame fraction t in [0,1], return per-joint local rotations. */
  poseAt: (t: number) => Record<number, [number, number, number, number]>
  beats?: (frameCount: number, fps: number) => BeatMarker[]
}

function buildMotion(spec: MotionSpec): MotionData {
  const fps = spec.fps
  const frameCount = Math.max(1, Math.round(spec.duration * fps))
  const poses: FramePose[] = []
  const pelvisRest = SMPL24_REST_POSE[SkeletonJoint.PELVIS]

  for (let f = 0; f < frameCount; f++) {
    const t = frameCount === 1 ? 0 : f / (frameCount - 1)
    const rotations = spec.poseAt(t)
    const transforms: Record<number, JointTransform> = {}
    for (const k of Object.keys(rotations)) {
      transforms[Number(k)] = { rotation: rotations[Number(k)] }
    }
    // Pelvis holds the (constant) world position.
    transforms[SkeletonJoint.PELVIS] = {
      rotation: transforms[SkeletonJoint.PELVIS]?.rotation ?? qIdentity(),
      position: [pelvisRest[0], pelvisRest[1], pelvisRest[2]]
    }
    poses.push({ frame: f, transforms })
  }

  const now = new Date().toISOString()
  return {
    id: uuid(),
    name: spec.name,
    description: spec.description,
    tags: spec.tags,
    fps,
    duration: spec.duration,
    frameCount,
    skeletonType: 'smpl_24',
    poses,
    beatMarkers: spec.beats ? spec.beats(frameCount, fps) : [],
    keyframeFlags: [],
    motionIntensity: 0.5,
    primaryJoints: [SkeletonJoint.L_WRIST, SkeletonJoint.R_WRIST],
    isLoopable: spec.name.includes('Circle'),
    source: 'manual',
    createdAt: now,
    updatedAt: now
  }
}

const TPOSE: MotionSpec = {
  name: 'T-Pose (静止)',
  description: 'Rest pose, 1 second.',
  tags: ['test', 't-pose'],
  fps: 30,
  duration: 1,
  poseAt: () => ({})
}

const CIRCLE: MotionSpec = {
  name: 'Left Arm Circle (画圆)',
  description: 'Left arm traces a circle in front, 3s loop.',
  tags: ['test', 'circle', 'loop'],
  fps: 30,
  duration: 3,
  poseAt: (t) => {
    // Trace a cone in the front-left quadrant: a horizontal sweep (±60° yaw)
    // combined with a vertical lift (±60° elevation), 90° out of phase so the
    // hand draws a circle. The arm direction stays at world x = cos(yaw)·cos(elev)
    // > 0, i.e. ALWAYS on the character's left side — it never crosses the body
    // midline or clips through the right arm (the previous full-360° yaw bug).
    const phase = t * Math.PI * 2
    const yaw = Math.cos(phase) * (Math.PI / 3)
    const elev = Math.sin(phase) * (Math.PI / 3)
    const qYaw = Quaternion.RotationAxis(new Vector3(0, 1, 0), yaw)
    const qElev = Quaternion.RotationAxis(new Vector3(0, 0, 1), elev)
    const q = qYaw.multiply(qElev) // lift first, then sweep
    return {
      [SkeletonJoint.L_SHOULDER]: [q.x, q.y, q.z, q.w],
      [SkeletonJoint.L_ELBOW]: qAxis([0, 0, 1], 0.25)
    }
  },
  beats: (fc) => [
    { frame: 0, beat: '1', type: 'downbeat', label: 'loop start' },
    { frame: Math.round(fc / 2), beat: '2', type: 'transition', label: 'half' }
  ]
}

const BOW: MotionSpec = {
  name: 'Bow (鞠躬)',
  description: 'Spine chain bends forward and back, 2s.',
  tags: ['test', 'bow'],
  fps: 30,
  duration: 2,
  poseAt: (t) => {
    // ease in/out sine, peak bend at t=0.5
    const bend = Math.sin(t * Math.PI) * 0.6
    const spineRot = qAxis([1, 0, 0], bend)
    return {
      [SkeletonJoint.SPINE_1]: spineRot,
      [SkeletonJoint.SPINE_2]: spineRot,
      [SkeletonJoint.SPINE_3]: spineRot,
      [SkeletonJoint.NECK]: qAxis([1, 0, 0], bend * 0.3)
    }
  }
}

/** Create the three built-in sample motions and import them into the library. */
export async function createSampleMotions(): Promise<void> {
  const store = useMotionStore.getState()
  for (const spec of [TPOSE, CIRCLE, BOW]) {
    const data = buildMotion(spec)
    await store.importMotion(data)
  }
}
