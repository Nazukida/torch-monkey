/**
 * SMPL-24 internal skeleton — single source of truth for the renderer side.
 *
 * ⚠️ This MUST stay byte-for-byte consistent with python/lib/skeleton_def.py
 * (names, parent indices, and rest pose in meters). The Python IK solver and
 * the TS skeleton rig are built from the same numbers, otherwise captured
 * motions will not retarget/play correctly.
 */

export enum SkeletonJoint {
  PELVIS = 0,
  L_HIP = 1,
  R_HIP = 2,
  SPINE_1 = 3,
  L_KNEE = 4,
  R_KNEE = 5,
  SPINE_2 = 6,
  L_ANKLE = 7,
  R_ANKLE = 8,
  SPINE_3 = 9,
  L_FOOT = 10,
  R_FOOT = 11,
  NECK = 12,
  L_COLLAR = 13,
  R_COLLAR = 14,
  HEAD = 15,
  L_SHOULDER = 16,
  R_SHOULDER = 17,
  L_ELBOW = 18,
  R_ELBOW = 19,
  L_WRIST = 20,
  R_WRIST = 21,
  // Extended joints (glowstick bind targets), derived from the wrists.
  L_HAND = 22,
  R_HAND = 23
}

export const SKELETON_JOINT_COUNT = 24

/** Parent joint index, or null for the root. */
export const SKELETON_PARENTS: (SkeletonJoint | null)[] = [
  null, // 0 PELVIS
  SkeletonJoint.PELVIS, // 1 L_HIP
  SkeletonJoint.PELVIS, // 2 R_HIP
  SkeletonJoint.PELVIS, // 3 SPINE_1
  SkeletonJoint.L_HIP, // 4 L_KNEE
  SkeletonJoint.R_HIP, // 5 R_KNEE
  SkeletonJoint.SPINE_1, // 6 SPINE_2
  SkeletonJoint.L_KNEE, // 7 L_ANKLE
  SkeletonJoint.R_KNEE, // 8 R_ANKLE
  SkeletonJoint.SPINE_2, // 9 SPINE_3
  SkeletonJoint.L_ANKLE, // 10 L_FOOT
  SkeletonJoint.R_ANKLE, // 11 R_FOOT
  SkeletonJoint.SPINE_3, // 12 NECK
  SkeletonJoint.SPINE_3, // 13 L_COLLAR
  SkeletonJoint.SPINE_3, // 14 R_COLLAR
  SkeletonJoint.NECK, // 15 HEAD
  SkeletonJoint.L_COLLAR, // 16 L_SHOULDER
  SkeletonJoint.R_COLLAR, // 17 R_SHOULDER
  SkeletonJoint.L_SHOULDER, // 18 L_ELBOW
  SkeletonJoint.R_SHOULDER, // 19 R_ELBOW
  SkeletonJoint.L_ELBOW, // 20 L_WRIST
  SkeletonJoint.R_ELBOW, // 21 R_WRIST
  SkeletonJoint.L_WRIST, // 22 L_HAND
  SkeletonJoint.R_WRIST // 23 R_HAND
]

export const SKELETON_JOINT_NAMES: Record<SkeletonJoint, string> = {
  [SkeletonJoint.PELVIS]: 'pelvis',
  [SkeletonJoint.L_HIP]: 'left_hip',
  [SkeletonJoint.R_HIP]: 'right_hip',
  [SkeletonJoint.SPINE_1]: 'spine_1',
  [SkeletonJoint.L_KNEE]: 'left_knee',
  [SkeletonJoint.R_KNEE]: 'right_knee',
  [SkeletonJoint.SPINE_2]: 'spine_2',
  [SkeletonJoint.L_ANKLE]: 'left_ankle',
  [SkeletonJoint.R_ANKLE]: 'right_ankle',
  [SkeletonJoint.SPINE_3]: 'spine_3',
  [SkeletonJoint.L_FOOT]: 'left_foot',
  [SkeletonJoint.R_FOOT]: 'right_foot',
  [SkeletonJoint.NECK]: 'neck',
  [SkeletonJoint.L_COLLAR]: 'left_collar',
  [SkeletonJoint.R_COLLAR]: 'right_collar',
  [SkeletonJoint.HEAD]: 'head',
  [SkeletonJoint.L_SHOULDER]: 'left_shoulder',
  [SkeletonJoint.R_SHOULDER]: 'right_shoulder',
  [SkeletonJoint.L_ELBOW]: 'left_elbow',
  [SkeletonJoint.R_ELBOW]: 'right_elbow',
  [SkeletonJoint.L_WRIST]: 'left_wrist',
  [SkeletonJoint.R_WRIST]: 'right_wrist',
  [SkeletonJoint.L_HAND]: 'left_hand',
  [SkeletonJoint.R_HAND]: 'right_hand'
}

/**
 * T-pose rest joint positions, meters, Y-up, root near (0, 0.9, 0).
 * Mirrors python/lib/skeleton_def.py:SMPL24_REST_POSE exactly.
 */
export const SMPL24_REST_POSE: [number, number, number][] = [
  [0.0, 0.9, 0.0], // 0 PELVIS
  [0.1, 0.86, 0.0], // 1 L_HIP
  [-0.1, 0.86, 0.0], // 2 R_HIP
  [0.0, 1.0, 0.0], // 3 SPINE_1
  [0.1, 0.45, 0.0], // 4 L_KNEE
  [-0.1, 0.45, 0.0], // 5 R_KNEE
  [0.0, 1.1, 0.0], // 6 SPINE_2
  [0.1, 0.05, 0.0], // 7 L_ANKLE
  [-0.1, 0.05, 0.0], // 8 R_ANKLE
  [0.0, 1.22, 0.0], // 9 SPINE_3
  [0.1, 0.02, 0.12], // 10 L_FOOT
  [-0.1, 0.02, 0.12], // 11 R_FOOT
  [0.0, 1.4, 0.0], // 12 NECK
  [0.08, 1.34, 0.0], // 13 L_COLLAR
  [-0.08, 1.34, 0.0], // 14 R_COLLAR
  [0.0, 1.55, 0.0], // 15 HEAD
  [0.18, 1.36, 0.0], // 16 L_SHOULDER
  [-0.18, 1.36, 0.0], // 17 R_SHOULDER
  [0.45, 1.36, 0.0], // 18 L_ELBOW
  [-0.45, 1.36, 0.0], // 19 R_ELBOW
  [0.7, 1.36, 0.0], // 20 L_WRIST
  [-0.7, 1.36, 0.0], // 21 R_WRIST
  [0.8, 1.36, 0.0], // 22 L_HAND
  [-0.8, 1.36, 0.0] // 23 R_HAND
]

/** Joints to emphasize for kime detection / intensity stats (upper body). */
export const UPPER_BODY_JOINTS: SkeletonJoint[] = [
  SkeletonJoint.L_SHOULDER,
  SkeletonJoint.R_SHOULDER,
  SkeletonJoint.L_ELBOW,
  SkeletonJoint.R_ELBOW,
  SkeletonJoint.L_WRIST,
  SkeletonJoint.R_WRIST,
  SkeletonJoint.L_HAND,
  SkeletonJoint.R_HAND
]

/** Joints glowsticks bind to. */
export const GLOWSTICK_BIND_JOINTS = {
  left: SkeletonJoint.L_HAND,
  right: SkeletonJoint.R_HAND
}

/** Default overall character height to scale the rest pose against. */
export const REFERENCE_REST_HEIGHT = 1.55

/**
 * Returns the rest-pose offset of a joint relative to its parent (the bone
 * vector as it sits in the parent's local frame at rest).
 */
export function restBoneOffset(joint: SkeletonJoint): [number, number, number] {
  const parent = SKELETON_PARENTS[joint]
  const p = SMPL24_REST_POSE[joint]
  if (parent === null) return [p[0], p[1], p[2]]
  const q = SMPL24_REST_POSE[parent]
  return [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
}

/** Children of each joint (convenience for procedural mesh building). */
export const SKELETON_CHILDREN: SkeletonJoint[][] = (() => {
  const children: SkeletonJoint[][] = Array.from({ length: SKELETON_JOINT_COUNT }, () => [])
  for (let j = 0; j < SKELETON_JOINT_COUNT; j++) {
    const p = SKELETON_PARENTS[j]
    if (p !== null) children[p].push(j as SkeletonJoint)
  }
  return children
})()
