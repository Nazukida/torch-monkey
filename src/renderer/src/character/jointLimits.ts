import { Quaternion, Vector3 } from '@babylonjs/core'
import { SkeletonJoint, restBoneOffset } from '@shared/constants/skeleton'
import type { FramePose, JointTransform } from '@shared/types/motion'

/**
 * Anatomical joint limits applied to a rendered pose so no motion — preset or
 * AI-captured — can drive a limb into an impossible / 穿模 pose.
 *
 * The limits are deliberately generous: they only intervene on clearly
 * impossible configurations, so realistic motion (large wotagei gestures,
 * overhead raises, arms crossing in front of the chest, …) passes through
 * UNCHANGED. Every check has an allocation-free fast path that returns the
 * input transform by reference, so the clamp is effectively free for any
 * in-range pose.
 *
 * What each limit actually enforces:
 *  - Shoulder (ball joint): the upper-arm bone may not cross the body midline
 *    onto the opposite side — the classic 穿模 where an arm sweeps through the
 *    torso to the other side. It is detected geometrically from the rotated
 *    bone direction, so the crossing is caught no matter which rotation axis
 *    expressed it (a horizontal yaw sweep OR an overhead "up-and-over" rotation
 *    both move the bone across the midline and both are blocked).
 *  - Hinge (elbow/knee): caps the maximum FOLD (over-flexion) angle — the joint
 *    can't fold flatter than is anatomically possible.
 *
 * Known limitation: the hinge clamp measures an UNSIGNED fold angle, so it caps
 * over-flexion but does NOT detect hyperextension (a small backward bend past
 * straight). Blocking that needs a signed, per-joint flexion-axis test with a
 * verified sign convention; it is intentionally deferred to avoid the risk of
 * blocking legitimate flexion. See {@link clampHinge}.
 */
const DEG = Math.PI / 180

// Shoulder: block the upper-arm from crossing the body midline. The bone rests
// along ±X in the shoulder's local frame, so its x-component after rotation is a
// direct measure of which side of the body the arm is on. The arm may reach the
// centre line and a hair past it, but not onto the opposite side.
// SHOULDER_CROSS_X is the most-negative x the bone may point to; cos(100°)
// reproduces the historical ±100° horizontal-yaw intent but applied to the real
// bone direction so vertical/overhead crossings are caught too.
const SHOULDER_YAW_MAX = 100 * DEG
const SHOULDER_CROSS_X = Math.cos(SHOULDER_YAW_MAX) // ≈ -0.1736

// Hinge (elbow/knee) max fold: the unsigned angle between the rest bone
// direction and the rotated bone direction. Caps only the over-flexion range.
const ELBOW_FOLD_MAX = 165 * DEG
const KNEE_FOLD_MAX = 170 * DEG

const SHOULDER_JOINTS = new Set<number>([SkeletonJoint.L_SHOULDER, SkeletonJoint.R_SHOULDER])
const HINGE_FOLD_MAX: Record<number, number> = {
  [SkeletonJoint.L_ELBOW]: ELBOW_FOLD_MAX,
  [SkeletonJoint.R_ELBOW]: ELBOW_FOLD_MAX,
  [SkeletonJoint.L_KNEE]: KNEE_FOLD_MAX,
  [SkeletonJoint.R_KNEE]: KNEE_FOLD_MAX
}
/** Child joint whose rest offset defines the bone the hinge rotates (forearm/shin). */
const HINGE_CHILD: Record<number, SkeletonJoint> = {
  [SkeletonJoint.L_ELBOW]: SkeletonJoint.L_WRIST,
  [SkeletonJoint.R_ELBOW]: SkeletonJoint.R_WRIST,
  [SkeletonJoint.L_KNEE]: SkeletonJoint.L_ANKLE,
  [SkeletonJoint.R_KNEE]: SkeletonJoint.R_ANKLE
}

// Hoist the rest bone directions to module constants so the per-frame path
// doesn't recompute (and re-allocate) them every call.
const REST_ARM_DIR: Record<number, Vector3> = {
  [SkeletonJoint.L_SHOULDER]: Vector3.FromArray(restBoneOffset(SkeletonJoint.L_ELBOW)).normalize(),
  [SkeletonJoint.R_SHOULDER]: Vector3.FromArray(restBoneOffset(SkeletonJoint.R_ELBOW)).normalize()
}
const REST_HINGE_DIR: Record<number, Vector3> = {
  [SkeletonJoint.L_ELBOW]: Vector3.FromArray(restBoneOffset(HINGE_CHILD[SkeletonJoint.L_ELBOW])).normalize(),
  [SkeletonJoint.R_ELBOW]: Vector3.FromArray(restBoneOffset(HINGE_CHILD[SkeletonJoint.R_ELBOW])).normalize(),
  [SkeletonJoint.L_KNEE]: Vector3.FromArray(restBoneOffset(HINGE_CHILD[SkeletonJoint.L_KNEE])).normalize(),
  [SkeletonJoint.R_KNEE]: Vector3.FromArray(restBoneOffset(HINGE_CHILD[SkeletonJoint.R_KNEE])).normalize()
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/** Shortest rotation taking unit vector `from` to unit vector `to`. */
function fromToRotation(from: Vector3, to: Vector3): Quaternion {
  const dot = Vector3.Dot(from, to)
  if (dot > 0.999999) return Quaternion.Identity()
  if (dot < -0.999999) {
    const axis = Math.abs(from.x) < 0.9 ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0)
    return Quaternion.RotationAxis(Vector3.Cross(from, axis).normalize(), Math.PI)
  }
  return Quaternion.RotationAxis(Vector3.Cross(from, to).normalize(), Math.acos(clamp(dot, -1, 1)))
}

/**
 * Limit a shoulder ball joint: if the upper-arm bone has crossed the body
 * midline onto the opposite side, rotate it back to the boundary (preserving
 * the arm's elevation and axial twist). Every in-range pose hits the
 * allocation-free fast path and is returned verbatim.
 */
function clampShoulder(rot: [number, number, number, number], joint: number): [number, number, number, number] {
  // Fast path (no allocation): for a ±X rest bone the rotated bone's
  // x-component (in shoulder-local space) is 1 − 2(qy² + qz²), and that equals
  // ownSign·cur.x for BOTH shoulders. If it is within the allowed crossing
  // margin the pose is on the correct side — return it by reference.
  const fastX = 1 - 2 * (rot[1] * rot[1] + rot[2] * rot[2])
  if (fastX >= SHOULDER_CROSS_X) return rot

  // Crossed — remap the bone direction back to the midline boundary.
  const rest = REST_ARM_DIR[joint]
  const ownSign = rest.x > 0 ? 1 : -1
  const q = new Quaternion(rot[0], rot[1], rot[2], rot[3])
  const cur = rest.applyRotationQuaternion(q)
  cur.normalize()

  // Boundary direction: same elevation (cur.y) and the same horizontal reach /
  // z-sign, but x pinned to the allowed edge.
  const boundaryX = SHOULDER_CROSS_X * ownSign
  const h2 = cur.x * cur.x + cur.z * cur.z
  const newZ = (cur.z >= 0 ? 1 : -1) * Math.sqrt(Math.max(0, h2 - boundaryX * boundaryX))
  const clamped = new Vector3(boundaryX, cur.y, newZ)
  clamped.normalize()

  // Preserve the arm's axial twist via swing-twist decomposition and only remap
  // the swing: q = swing·twist, so twist = swing⁻¹·q, and q' = swing'·twist.
  const swing = fromToRotation(rest, cur)
  const swingClamped = fromToRotation(rest, clamped)
  const twist = swing.conjugate().multiply(q)
  const out = swingClamped.multiply(twist)
  return [out.x, out.y, out.z, out.w]
}

/**
 * Limit a 1-DOF hinge (elbow/knee): cap the unsigned FOLD angle to `maxFold` so
 * the joint can't fold flatter than is anatomically possible. Returns the pose
 * verbatim when within range.
 *
 * NOTE: this measures an UNSIGNED angle, so it caps OVER-FLEXION only. It does
 * NOT detect hyperextension (a backward bend past straight), which is a small
 * fold in the opposite rotational direction. Detecting that requires a signed
 * angle about a per-joint flexion axis with a verified sign convention; it is
 * intentionally not implemented here to avoid the risk of blocking legitimate
 * flexion.
 */
function clampHinge(
  rot: [number, number, number, number],
  joint: number,
  maxFold: number
): [number, number, number, number] {
  const rest = REST_HINGE_DIR[joint]
  const q = new Quaternion(rot[0], rot[1], rot[2], rot[3])
  const cur = rest.applyRotationQuaternion(q) // current bone direction
  if (cur.lengthSquared() < 1e-12) return rot
  cur.normalize()
  const dot = clamp(Vector3.Dot(rest, cur), -1, 1)
  const fold = Math.acos(dot) // 0 = straight
  if (fold <= maxFold) return rot // within limit — exact pass-through
  // Too far: scale the rotation back toward rest so the fold == maxFold.
  const clamped = Quaternion.Slerp(Quaternion.Identity(), q, maxFold / fold)
  return [clamped.x, clamped.y, clamped.z, clamped.w]
}

/**
 * Return a copy of `pose` with every joint rotation clamped to its anatomical
 * range. Joints without a configured limit (spine, neck, wrists, …) and every
 * within-range joint share the input transform by reference; if NO joint needed
 * clamping, the input `pose` is returned unchanged (zero allocation on the
 * common all-in-range path). The root (pelvis) position is preserved.
 * SkeletonRig.applyPose reads transforms read-only, so sharing by reference is
 * safe.
 */
export function clampPose(pose: FramePose): FramePose {
  const src = pose.transforms
  let changed = false
  const transforms: Record<number, JointTransform> = {}
  for (const key of Object.keys(src)) {
    const idx = Number(key)
    const t = src[idx]
    if (!t) continue
    let rot = t.rotation
    if (SHOULDER_JOINTS.has(idx)) {
      const clamped = clampShoulder(rot, idx)
      if (clamped !== rot) {
        rot = clamped
        changed = true
      }
    } else if (HINGE_FOLD_MAX[idx] !== undefined) {
      const clamped = clampHinge(rot, idx, HINGE_FOLD_MAX[idx])
      if (clamped !== rot) {
        rot = clamped
        changed = true
      }
    }
    transforms[idx] =
      rot === t.rotation ? t : { rotation: rot, ...(t.position ? { position: t.position } : {}) }
  }
  return changed ? { frame: pose.frame, transforms } : pose
}
