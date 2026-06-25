import {
  Scene,
  TransformNode,
  Vector3,
  Quaternion,
  Mesh,
  MeshBuilder,
  StandardMaterial,
  Color3,
  AbstractMesh,
  ShadowGenerator,
  SceneLoader
} from '@babylonjs/core'
import { SkeletonRig } from './SkeletonRig'
import {
  SkeletonJoint,
  SKELETON_PARENTS,
  SKELETON_JOINT_COUNT,
  SMPL24_REST_POSE,
  restBoneOffset,
  REFERENCE_REST_HEIGHT
} from '@shared/constants/skeleton'
import type { CharacterConfig } from '@shared/types/character'
import type { FramePose } from '@shared/types/motion'

function hexToColor3(hex: string): Color3 {
  const m = hex.replace('#', '')
  return new Color3(
    parseInt(m.substring(0, 2), 16) / 255,
    parseInt(m.substring(2, 4), 16) / 255,
    parseInt(m.substring(4, 6), 16) / 255
  )
}

/** Quaternion rotating unit vector `from` onto unit vector `to` (robust). */
function quatFromTo(from: Vector3, to: Vector3): Quaternion {
  const f = Vector3.Normalize(from)
  const t = Vector3.Normalize(to)
  const dot = Vector3.Dot(f, t)
  if (dot > 0.999999) return Quaternion.Identity()
  if (dot < -0.999999) {
    // 180°: pick any perpendicular axis
    const axis =
      Math.abs(f.x) < 0.9 ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0)
    const ortho = Vector3.Normalize(Vector3.Cross(f, axis))
    return Quaternion.RotationAxis(ortho, Math.PI)
  }
  const axis = Vector3.Normalize(Vector3.Cross(f, t))
  const angle = Math.acos(Math.max(-1, Math.min(1, dot)))
  return Quaternion.RotationAxis(axis, angle)
}

/**
 * A placed character on the stage. Wraps a {@link SkeletonRig} plus a procedural
 * humanoid mesh (default) or a loaded glTF model. Motion playback is handled by
 * {@link MotionPlayer}; this class only exposes joint world transforms (used by
 * the VFX layer for glowstick binding).
 */
export class CharacterModel {
  readonly id: string
  config: CharacterConfig
  readonly rig: SkeletonRig
  private meshes: AbstractMesh[] = []
  private material: StandardMaterial | null = null

  private constructor(id: string, config: CharacterConfig, scene: Scene) {
    this.id = id
    this.config = config
    this.rig = new SkeletonRig(id, scene)

    // Stage placement + facing on the placement root.
    this.rig.root.position = new Vector3(...config.position)
    this.rig.root.rotation = new Vector3(0, (config.rotation * Math.PI) / 180, 0)
    this.applyScale(config.bodyScale)
    this.rig.root.setEnabled(config.visible)
  }

  static createProcedural(
    id: string,
    config: CharacterConfig,
    scene: Scene
  ): CharacterModel {
    const model = new CharacterModel(id, config, scene)
    model.buildProceduralMesh(scene)
    model.setColor(config.color)
    model.setOpacity(config.opacity)
    return model
  }

  static async loadFromGLTF(
    id: string,
    config: CharacterConfig,
    scene: Scene,
    url: string
  ): Promise<CharacterModel> {
    const model = new CharacterModel(id, config, scene)
    const result = await SceneLoader.ImportMeshAsync(null, '', url, scene)
    // Parent loaded root meshes under the rig placement for consistent transform.
    const root = new TransformNode(`${id}__glbRoot`, scene)
    root.parent = model.rig.root
    for (const mesh of result.meshes) {
      if (!mesh.parent) mesh.parent = root
      model.meshes.push(mesh as AbstractMesh)
    }
    // Note: mapping the loaded skeleton onto our SMPL-24 rig is handled by
    // Retargeter at the MotionData level, not here.
    return model
  }

  private buildProceduralMesh(scene: Scene): void {
    const mat = new StandardMaterial(`${this.id}__mat`, scene)
    mat.diffuseColor = hexToColor3(this.config.color)
    mat.specularColor = new Color3(0.1, 0.1, 0.12)
    mat.specularPower = 32
    mat.alpha = this.config.opacity
    this.material = mat

    // A bone capsule for every joint that has a parent, plus joint spheres.
    for (let j = 0; j < SKELETON_JOINT_COUNT; j++) {
      const parentIdx = SKELETON_PARENTS[j as SkeletonJoint]
      const offset = restBoneOffset(j as SkeletonJoint)
      const offsetVec = new Vector3(offset[0], offset[1], offset[2])
      const length = offsetVec.length()

      // Joint sphere
      const radius = this.jointRadius(j as SkeletonJoint)
      const sph = MeshBuilder.CreateSphere(`${this.id}__j_${j}`, { diameter: radius * 2, segments: 8 }, scene)
      sph.material = mat
      sph.parent = this.rig.getJointNode(j as SkeletonJoint)
      this.meshes.push(sph)

      if (parentIdx !== null && length > 1e-4) {
        const parentNode = this.rig.getJointNode(parentIdx as SkeletonJoint)
        const boneRadius = this.boneRadius(j as SkeletonJoint)
        const cyl = MeshBuilder.CreateCylinder(
          `${this.id}__b_${j}`,
          { height: length, diameter: boneRadius * 2, tessellation: 8 },
          scene
        )
        cyl.material = mat
        cyl.parent = parentNode
        // Orient default Y axis onto the bone offset, place midpoint at offset/2.
        cyl.rotationQuaternion = quatFromTo(Vector3.Up(), offsetVec)
        cyl.position = offsetVec.scale(0.5)
        this.meshes.push(cyl)
      }
    }

    // A slightly larger head sphere for readability.
    const head = MeshBuilder.CreateSphere(`${this.id}__head`, { diameter: 0.22, segments: 12 }, scene)
    head.material = mat
    head.parent = this.rig.getJointNode(SkeletonJoint.HEAD)
    head.position = new Vector3(0, 0.06, 0)
    this.meshes.push(head)
  }

  private jointRadius(j: SkeletonJoint): number {
    if (j === SkeletonJoint.HEAD) return 0.11
    if (j === SkeletonJoint.PELVIS) return 0.09
    return 0.045
  }

  private boneRadius(j: SkeletonJoint): number {
    switch (j) {
      case SkeletonJoint.SPINE_1:
      case SkeletonJoint.SPINE_2:
      case SkeletonJoint.SPINE_3:
      case SkeletonJoint.NECK:
        return 0.07
      case SkeletonJoint.L_HIP:
      case SkeletonJoint.R_HIP:
      case SkeletonJoint.L_KNEE:
      case SkeletonJoint.R_KNEE:
        return 0.06
      case SkeletonJoint.L_SHOULDER:
      case SkeletonJoint.R_SHOULDER:
      case SkeletonJoint.L_ELBOW:
      case SkeletonJoint.R_ELBOW:
        return 0.04
      case SkeletonJoint.L_FOOT:
      case SkeletonJoint.R_FOOT:
        return 0.05
      default:
        return 0.03
    }
  }

  registerShadows(generator: ShadowGenerator | null): void {
    if (!generator) return
    for (const m of this.meshes) {
      if (m instanceof Mesh) generator.addShadowCaster(m)
    }
  }

  applyScale(scale: number): void {
    this.rig.root.scaling = new Vector3(scale, scale, scale)
  }

  setColor(hex: string): void {
    this.config.color = hex
    if (this.material) this.material.diffuseColor = hexToColor3(hex)
  }

  setOpacity(alpha: number): void {
    this.config.opacity = alpha
    if (this.material) {
      this.material.alpha = alpha
      this.material.transparencyMode = alpha < 1 ? 1 : 0
    }
  }

  setVisible(visible: boolean): void {
    this.config.visible = visible
    this.rig.root.setEnabled(visible)
  }

  setShowSkeleton(show: boolean, scene: Scene): void {
    this.config.showSkeleton = show
    this.rig.visualizeDebug(scene, show)
  }

  setPosition(x: number, y: number, z: number): void {
    this.config.position = [x, y, z]
    this.rig.root.position = new Vector3(x, y, z)
  }

  setRotationDeg(deg: number): void {
    this.config.rotation = deg
    this.rig.root.rotation = new Vector3(0, (deg * Math.PI) / 180, 0)
  }

  getJointWorldPosition(joint: SkeletonJoint): Vector3 {
    return this.rig.getJointWorldPosition(joint)
  }

  getJointWorldRotation(joint: SkeletonJoint): Quaternion {
    return this.rig.getJointWorldRotation(joint)
  }

  applyPose(pose: FramePose, rootOrigin?: [number, number, number]): void {
    this.rig.applyPose(pose, rootOrigin)
  }

  resetToRestPose(): void {
    this.rig.resetToRestPose()
  }

  frameUpdate(): void {
    this.rig.updateDebug()
  }

  dispose(): void {
    for (const m of this.meshes) m.dispose()
    this.material?.dispose()
    this.rig.dispose()
  }

  static get referenceHeight(): number {
    return REFERENCE_REST_HEIGHT
  }

  /** Head-top height of the rest pose in meters (used to derive bodyScale). */
  static get restHeadTop(): number {
    return SMPL24_REST_POSE[SkeletonJoint.HEAD][1]
  }
}
