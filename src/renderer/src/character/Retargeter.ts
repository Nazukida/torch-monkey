import { Quaternion } from '@babylonjs/core'
import { v4 as uuid } from 'uuid'
import { SkeletonJoint } from '@shared/constants/skeleton'
import type { MotionData, FramePose, JointTransform } from '@shared/types/motion'

/**
 * Retargets a standard SMPL-24 motion onto a target skeleton whose joint order
 * or T-pose differs (e.g. a user-imported glTF). The offset compensation follows
 * the standard convention: tgtRot = offset * srcRot * offset⁻¹, which removes the
 * difference between the two rest poses so the pose reads correctly on the target.
 */
export interface RetargetOptions {
  /** Source SkeletonJoint -> target joint index. */
  jointMap: Map<SkeletonJoint, number>
  /** Per-source-joint T-pose correction quaternion (target rest vs source rest). */
  restPoseOffset?: Map<SkeletonJoint, Quaternion>
  nameSuffix?: string
}

export class Retargeter {
  static retarget(source: MotionData, options: RetargetOptions): MotionData {
    const { jointMap, restPoseOffset } = options
    const retargetedPoses: FramePose[] = []

    for (const srcPose of source.poses) {
      const transforms: Record<number, JointTransform> = {}

      for (const [srcJoint, tgtIndex] of jointMap) {
        const srcTransform = srcPose.transforms[srcJoint]
        if (!srcTransform) continue

        const srcRot = new Quaternion(
          srcTransform.rotation[0],
          srcTransform.rotation[1],
          srcTransform.rotation[2],
          srcTransform.rotation[3]
        )
        const offset = restPoseOffset?.get(srcJoint) ?? Quaternion.Identity()
        const tgtRot = offset.multiply(srcRot).multiply(Quaternion.Inverse(offset))

        transforms[tgtIndex] = {
          rotation: [tgtRot.x, tgtRot.y, tgtRot.z, tgtRot.w]
        }

        // Root translation travels with the pelvis.
        if (srcJoint === SkeletonJoint.PELVIS && srcTransform.position) {
          transforms[tgtIndex].position = [...srcTransform.position] as [
            number,
            number,
            number
          ]
        }
      }

      retargetedPoses.push({ frame: srcPose.frame, transforms })
    }

    const now = new Date().toISOString()
    return {
      ...source,
      id: uuid(),
      name: `${source.name}${options.nameSuffix ? options.nameSuffix : ' (retargeted)'}`,
      poses: retargetedPoses,
      updatedAt: now
    }
  }
}
