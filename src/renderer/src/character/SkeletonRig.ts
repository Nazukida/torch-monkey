import {
  Scene,
  TransformNode,
  Quaternion,
  Vector3,
  MeshBuilder,
  Color3,
  StandardMaterial,
  Mesh,
  LinesMesh
} from '@babylonjs/core'
import {
  SkeletonJoint,
  SKELETON_PARENTS,
  SKELETON_JOINT_NAMES,
  SKELETON_JOINT_COUNT,
  SMPL24_REST_POSE,
  SKELETON_CHILDREN,
  restBoneOffset
} from '@shared/constants/skeleton'
import type { FramePose } from '@shared/types/motion'

/**
 * Presentation rest pose — the visual "ready" stance a performer returns to when
 * idle / reset / eased back after a clip ends: legs abducted to a 2× shoulder-
 * width spread, arms held horizontal (the SMPL T-pose).
 *
 * This is the DISPLAY-ONLY idle target. It MUST NOT change {@link SMPL24_REST_POSE}
 * (which stays byte-identical to python/lib/skeleton_def.py because captured-motion
 * rotations are authored local-to that T-pose). We express the wide stance as local
 * joint rotations layered on top of the unchanged rest offsets: a ±18° hip abduction
 * about the forward (Z) axis swings each foot ≈0.26 m outboard, landing the feet at
 * roughly twice shoulder width. The shoulder/elbow chain is left at identity so the
 * arms stay horizontal (照原样平举).
 */
const STANCE_ABDUCT_RAD = 18 * (Math.PI / 180)
const PRESENTATION_REST_ROT: Partial<Record<SkeletonJoint, Quaternion>> = {
  [SkeletonJoint.L_HIP]: Quaternion.RotationAxis(new Vector3(0, 0, 1), STANCE_ABDUCT_RAD),
  [SkeletonJoint.R_HIP]: Quaternion.RotationAxis(new Vector3(0, 0, 1), -STANCE_ABDUCT_RAD)
}

/** Local rest rotation for a joint in the presentation stance (identity outside the hips). */
function presentationRestRotation(j: SkeletonJoint): Quaternion {
  return PRESENTATION_REST_ROT[j] ?? Quaternion.Identity()
}

/**
 * Procedural SMPL-24 rig built from {@link shared/constants/skeleton}.
 *
 * Implementation note: we use a `TransformNode` per joint (parented per the
 * hierarchy) rather than a Babylon skinned Skeleton. FK is then automatic via
 * Babylon's world-matrix propagation, which keeps the applyPose / world-query
 * code trivial and avoids skinning math for the procedural fallback character.
 * The same joint indices/rotations map directly onto a loaded glTF Skeleton in
 * {@link CharacterModel} for custom models.
 */
export class SkeletonRig {
  readonly name: string
  readonly root: TransformNode // stage placement (world pos + Y facing)
  readonly nodes: TransformNode[] = []
  private sceneRef: Scene
  private debugMeshes: (LinesMesh | Mesh)[] = []
  private debugVisible = false

  constructor(name: string, scene: Scene) {
    this.sceneRef = scene
    this.name = name
    this.root = new TransformNode(`${name}__placement`, scene)

    for (let j = 0; j < SKELETON_JOINT_COUNT; j++) {
      const jointName = SKELETON_JOINT_NAMES[j as SkeletonJoint]
      const node = new TransformNode(`${name}__${jointName}`, scene)
      const parentIdx = SKELETON_PARENTS[j as SkeletonJoint]
      node.parent = parentIdx === null ? this.root : this.nodes[parentIdx]
      const off = restBoneOffset(j as SkeletonJoint)
      node.position = new Vector3(off[0], off[1], off[2])
      // Spawn already in the presentation (wide-stance) rest pose so a freshly
      // created character with no motion is immediately feet-apart, instead of
      // starting in the narrow SMPL T-pose and easing outward over 1-2 seconds.
      node.rotationQuaternion = presentationRestRotation(j as SkeletonJoint).clone()
      this.nodes.push(node)
    }
  }

  /**
   * Apply a single frame pose. Rotations are LOCAL (relative to the parent
   * bone), matching the Python IK solver output. The pelvis (joint 0) is the
   * motion root: its `position` is the rebased world trajectory relative to the
   * capture origin (i.e. relative to its first frame), so it drives on-stage
   * locomotion on top of the rest offset.
   *
   * @param pose            frame to apply
   * @param rootOrigin      world position of frame 0 (subtracted so motion
   *                        starts at the character origin); null = no rebase
   */
  applyPose(pose: FramePose, rootOrigin?: [number, number, number]): void {
    const pelvis = this.nodes[SkeletonJoint.PELVIS]
    const restOff = restBoneOffset(SkeletonJoint.PELVIS)

    for (const key of Object.keys(pose.transforms)) {
      const idx = Number(key)
      if (idx < 0 || idx >= SKELETON_JOINT_COUNT) continue
      const t = pose.transforms[idx]
      const node = this.nodes[idx]
      if (!node) continue

      const q = t.rotation
      node.rotationQuaternion = new Quaternion(q[0], q[1], q[2], q[3])

      if (idx === SkeletonJoint.PELVIS && t.position) {
        const [px, py, pz] = t.position
        const ox = rootOrigin ? rootOrigin[0] : 0
        const oy = rootOrigin ? rootOrigin[1] : 0
        const oz = rootOrigin ? rootOrigin[2] : 0
        node.position = new Vector3(
          restOff[0] + (px - ox),
          restOff[1] + (py - oy),
          restOff[2] + (pz - oz)
        )
      }
    }
  }

  resetToRestPose(): void {
    for (let j = 0; j < SKELETON_JOINT_COUNT; j++) {
      const node = this.nodes[j]
      node.rotationQuaternion = presentationRestRotation(j as SkeletonJoint).clone()
      const off = restBoneOffset(j as SkeletonJoint)
      node.position = new Vector3(off[0], off[1], off[2])
    }
  }

  /**
   * Ease every joint one step toward the presentation rest stance. Rotations
   * slerp toward {@link presentationRestRotation}; the pelvis additionally lerps
   * its position back to the rest offset (the only joint whose position ever
   * moves during playback). Non-pelvis joint positions are constant rest offsets,
   * so they need no position ease. `alpha` is the per-frame blend weight (0 = no
   * change, 1 = snap to rest); the caller derives it frame-rate-independently.
   */
  easeToRest(alpha: number): void {
    const a = Math.max(0, Math.min(1, alpha))
    if (a <= 0) return
    for (let j = 0; j < SKELETON_JOINT_COUNT; j++) {
      const node = this.nodes[j]
      const cur = node.rotationQuaternion ?? Quaternion.Identity()
      node.rotationQuaternion = Quaternion.Slerp(cur, presentationRestRotation(j as SkeletonJoint), a)
      if (j === SkeletonJoint.PELVIS) {
        const off = restBoneOffset(SkeletonJoint.PELVIS)
        node.position = Vector3.Lerp(
          node.position,
          new Vector3(off[0], off[1], off[2]),
          a
        )
      }
    }
  }

  getJointWorldPosition(joint: SkeletonJoint): Vector3 {
    const node = this.nodes[joint]
    node.computeWorldMatrix(true)
    return node.absolutePosition.clone()
  }

  getJointWorldRotation(joint: SkeletonJoint): Quaternion {
    const node = this.nodes[joint]
    node.computeWorldMatrix(true)
    return (node.absoluteRotationQuaternion ?? Quaternion.Identity()).clone()
  }

  getJointNode(joint: SkeletonJoint): TransformNode {
    return this.nodes[joint]
  }

  /** Attach a mesh so it follows a joint (e.g. a glowstick bound to the hand). */
  attachToJoint(joint: SkeletonJoint, node: TransformNode): void {
    node.parent = this.nodes[joint]
  }

  visualizeDebug(scene: Scene, visible: boolean): void {
    this.debugVisible = visible
    if (visible) {
      if (this.debugMeshes.length === 0) this.buildDebug(scene)
      this.debugMeshes.forEach((m) => (m.isVisible = true))
      // Refresh bone lines each frame the debug is on.
    } else {
      this.debugMeshes.forEach((m) => (m.isVisible = false))
    }
  }

  private buildDebug(scene: Scene): void {
    const mat = new StandardMaterial(`${this.name}__debugMat`, scene)
    mat.emissiveColor = new Color3(0.2, 0.8, 0.4)
    mat.disableLighting = true
    mat.wireframe = false

    for (let j = 0; j < SKELETON_JOINT_COUNT; j++) {
      const parentIdx = SKELETON_PARENTS[j as SkeletonJoint]
      if (parentIdx === null) {
        const sph = MeshBuilder.CreateSphere(`${this.name}__dbg_${j}`, { diameter: 0.06 }, scene)
        sph.parent = this.nodes[j]
        sph.material = mat
        this.debugMeshes.push(sph)
        continue
      }
      // Bone drawn as a thin line from parent node to this node (both in world).
      const parent = this.nodes[parentIdx]
      const child = this.nodes[j]
      const line = MeshBuilder.CreateLines(
        `${this.name}__dbgline_${j}`,
        { points: [Vector3.Zero(), Vector3.Zero()], updatable: true },
        scene
      )
      line.color = new Color3(0.3, 0.9, 0.5)
      line.parent = null
      ;(line as LinesMesh & { _rigParent: TransformNode; _rigChild: TransformNode })._rigParent =
        parent
      ;(line as LinesMesh & { _rigParent: TransformNode; _rigChild: TransformNode })._rigChild =
        child
      this.debugMeshes.push(line as LinesMesh)
    }
  }

  /** Call each frame to refresh the world-space debug bone lines. */
  updateDebug(): void {
    if (!this.debugVisible) return
    for (const m of this.debugMeshes) {
      const tagged = m as LinesMesh & {
        _rigParent?: TransformNode
        _rigChild?: TransformNode
      }
      if (tagged._rigParent && tagged._rigChild) {
        tagged._rigParent.computeWorldMatrix(true)
        tagged._rigChild.computeWorldMatrix(true)
        MeshBuilder.CreateLines(
          (tagged as LinesMesh).name,
          {
            points: [tagged._rigParent.absolutePosition, tagged._rigChild.absolutePosition],
            instance: tagged as LinesMesh,
            updatable: true
          },
          this.sceneRef
        )
      }
    }
  }

  isDebugVisible(): boolean {
    return this.debugVisible
  }

  dispose(): void {
    this.debugMeshes.forEach((m) => m.dispose())
    this.debugMeshes = []
    this.nodes.forEach((n) => n.dispose())
    this.root.dispose()
  }

  /** Convenience: SMPL child joints (used by the procedural mesh builder). */
  static getChildren(joint: SkeletonJoint): SkeletonJoint[] {
    return SKELETON_CHILDREN[joint]
  }
}
