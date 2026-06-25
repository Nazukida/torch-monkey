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
      node.rotationQuaternion = Quaternion.Identity()
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
      node.rotationQuaternion = Quaternion.Identity()
      const off = restBoneOffset(j as SkeletonJoint)
      node.position = new Vector3(off[0], off[1], off[2])
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
