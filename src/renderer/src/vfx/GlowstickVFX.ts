import {
  Scene,
  Mesh,
  MeshBuilder,
  PBRMaterial,
  PointLight,
  Color3,
  Vector3,
  Quaternion,
  Matrix,
  GlowLayer
} from '@babylonjs/core'
import { TrailRenderer } from './TrailRenderer'
import type { CharacterModel } from '@renderer/character/CharacterModel'
import { SkeletonJoint, SMPL24_REST_POSE } from '@shared/constants/skeleton'
import type { GlowstickConfig, GlowstickOptions } from '@shared/types/vfx'

function hexToColor3(hex: string): Color3 {
  const m = hex.replace('#', '')
  return new Color3(
    parseInt(m.substring(0, 2), 16) / 255,
    parseInt(m.substring(2, 4), 16) / 255,
    parseInt(m.substring(4, 6), 16) / 255
  )
}

function quatFromTo(from: Vector3, to: Vector3): Quaternion {
  const f = Vector3.Normalize(from)
  const t = Vector3.Normalize(to)
  const dot = Vector3.Dot(f, t)
  if (dot > 0.999999) return Quaternion.Identity()
  if (dot < -0.999999) {
    const axis = Math.abs(f.x) < 0.9 ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0)
    return Quaternion.RotationAxis(Vector3.Normalize(Vector3.Cross(f, axis)), Math.PI)
  }
  return Quaternion.RotationAxis(Vector3.Normalize(Vector3.Cross(f, t)), Math.acos(dot))
}

interface GlowstickInstance {
  stick: Mesh
  material: PBRMaterial
  light: PointLight
  trail: TrailRenderer
  bindJoint: SkeletonJoint
  color: Color3
}

/**
 * Manages glowsticks (cyalume) for characters: emissive stick mesh bound to the
 * hand joints, a small point light that washes the body, and a speed-adaptive
 * ribbon trail. The actual bloom comes from the shared {@link GlowLayer}.
 */
export class GlowstickVFX {
  private scene: Scene
  private glowLayer: GlowLayer
  private characters = new Map<string, GlowstickInstance[]>()
  /** Snapshot of the last config we pushed onto the scene, so a geometry-only
   *  change (length/radius/offsetAngle) triggers a rebuild instead of being
   *  silently dropped by the cheap in-place patch path. */
  private lastApplied: GlowstickConfig | null = null

  constructor(scene: Scene) {
    this.scene = scene
    this.glowLayer = new GlowLayer('glowstickGlow', scene)
    this.glowLayer.intensity = 1.2
  }

  getGlowLayer(): GlowLayer {
    return this.glowLayer
  }

  createForCharacter(characterId: string, character: CharacterModel, config: GlowstickConfig): void {
    this.removeCharacter(characterId)
    if (!config.enabled) return

    const instances: GlowstickInstance[] = []
    instances.push(this.createStick(characterId, character, SkeletonJoint.R_HAND, config.rightHand))
    instances.push(this.createStick(characterId, character, SkeletonJoint.L_HAND, config.leftHand))

    if (config.doubleWield) {
      instances.push(
        this.createStick(characterId + '_r2', character, SkeletonJoint.R_HAND, {
          ...config.rightHand,
          offsetAngle: 15
        })
      )
      instances.push(
        this.createStick(characterId + '_l2', character, SkeletonJoint.L_HAND, {
          ...config.leftHand,
          offsetAngle: 15
        })
      )
    }

    // Respect trail toggle.
    if (!config.trail) {
      for (const inst of instances) inst.trail.setEnabled(false)
    }

    this.characters.set(characterId, instances)
  }

  private createStick(
    tag: string,
    character: CharacterModel,
    bindJoint: SkeletonJoint,
    options: GlowstickOptions
  ): GlowstickInstance {
    const color = hexToColor3(options.color)

    const stick = MeshBuilder.CreateCylinder(
      `glowstick_${tag}_${bindJoint}`,
      { height: options.length, diameter: options.radius * 2, tessellation: 10 },
      this.scene
    )
    const mat = new PBRMaterial(`glowstickMat_${tag}_${bindJoint}`, this.scene)
    mat.albedoColor = color
    mat.emissiveColor = color.scale(options.intensity)
    mat.metallic = 0.1
    mat.roughness = 0.3
    mat.alpha = 0.95
    stick.material = mat
    stick.isPickable = false

    // Orient + place: extend outward from the hand along the wrist→hand direction.
    const handRest = Vector3.FromArray(SMPL24_REST_POSE[bindJoint])
    const wristJoint =
      bindJoint === SkeletonJoint.R_HAND ? SkeletonJoint.R_WRIST : SkeletonJoint.L_WRIST
    const wristRest = Vector3.FromArray(SMPL24_REST_POSE[wristJoint])
    let outward = handRest.subtract(wristRest)
    if (outward.lengthSquared() < 1e-8) outward = new Vector3(1, 0, 0)
    outward.normalize()

    if (options.offsetAngle) {
      const tilt = Quaternion.RotationAxis(new Vector3(0, 0, 1), (options.offsetAngle * Math.PI) / 180)
      const m = Matrix.Identity()
      tilt.toRotationMatrix(m)
      outward = Vector3.TransformNormal(outward, m)
    }

    character.rig.attachToJoint(bindJoint, stick)
    stick.rotationQuaternion = quatFromTo(Vector3.Up(), outward)
    stick.position = outward.scale(options.length * 0.5)

    const light = new PointLight(`glowLight_${tag}_${bindJoint}`, Vector3.Zero(), this.scene)
    light.diffuse = color
    light.intensity = options.lightIntensity
    light.range = 1.5

    const trail = new TrailRenderer(this.scene, color)

    return { stick, material: mat, light, trail, bindJoint, color }
  }

  /**
   * Apply live glowstick config changes to every character. Structural changes
   * (enable/disable, double-wield toggle) rebuild the sticks; scalar/color edits
   * (intensity, lightIntensity, color) patch materials + lights in place so a
   * slider drag stays cheap. `characters` is the live CharacterModel map.
   *
   * This is the apply-path the VFX panel was missing: without it every glowstick
   * control mutated the store but nothing pushed the change onto the scene.
   */
  applyGlowConfig(config: GlowstickConfig, characters: Iterable<[string, CharacterModel]>): void {
    const geomChanged = !this.lastApplied || this.geometryChanged(this.lastApplied, config)
    for (const [id, model] of characters) {
      const instances = this.characters.get(id)
      const want = config.enabled ? (config.doubleWield ? 4 : 2) : 0
      const have = instances?.length ?? 0
      if (want !== have || geomChanged) {
        // Structural change (enable flip / double-wield) OR a geometry change
        // (length/radius/offsetAngle — those are baked into the cylinder mesh
        // at create time and can't be patched in place) → rebuild this char.
        this.createForCharacter(id, model, config)
        continue
      }
      if (!instances || want === 0) continue
      for (const inst of instances) {
        const side = inst.bindJoint === SkeletonJoint.R_HAND ? config.rightHand : config.leftHand
        const color = hexToColor3(side.color)
        inst.material.albedoColor = color
        inst.material.emissiveColor = color.scale(side.intensity)
        inst.light.diffuse = color
        inst.light.intensity = side.lightIntensity
        inst.color = color
        inst.trail.setColor(color)
      }
    }
    this.lastApplied = config
  }

  /** True if any field that is baked into the cylinder mesh / stick orientation
   *  at create time differs — those require a rebuild, not an in-place patch. */
  private geometryChanged(a: GlowstickConfig, b: GlowstickConfig): boolean {
    return (
      a.enabled !== b.enabled ||
      a.doubleWield !== b.doubleWield ||
      a.leftHand.length !== b.leftHand.length ||
      a.leftHand.radius !== b.leftHand.radius ||
      a.leftHand.offsetAngle !== b.leftHand.offsetAngle ||
      a.rightHand.length !== b.rightHand.length ||
      a.rightHand.radius !== b.rightHand.radius ||
      a.rightHand.offsetAngle !== b.rightHand.offsetAngle
    )
  }

  /** Per-frame: keep the point light + trail pinned to the hand world position. */
  update(character: CharacterModel): void {
    const instances = this.characters.get(character.id)
    if (!instances) return
    for (const inst of instances) {
      const pos = character.getJointWorldPosition(inst.bindJoint)
      inst.light.position.copyFrom(pos)
      inst.trail.addPoint(pos)
    }
  }

  /** Triggered on a detected kime frame: collapse every trail sharply. */
  onKime(): void {
    for (const instances of this.characters.values()) {
      for (const inst of instances) inst.trail.clearRapidly()
    }
  }

  setTrailEnabled(enabled: boolean): void {
    for (const instances of this.characters.values()) {
      for (const inst of instances) inst.trail.setEnabled(enabled)
    }
  }

  setGlowIntensity(intensity: number): void {
    this.glowLayer.intensity = intensity
  }

  removeCharacter(characterId: string): void {
    const instances = this.characters.get(characterId)
    if (!instances) return
    for (const inst of instances) {
      // Mesh.dispose() defaults to disposeMaterialAndTextures=false, so the
      // per-stick PBRMaterial is orphaned unless we dispose it explicitly.
      inst.material.dispose()
      inst.stick.dispose()
      inst.light.dispose()
      inst.trail.dispose()
    }
    this.characters.delete(characterId)
  }

  dispose(): void {
    for (const id of Array.from(this.characters.keys())) this.removeCharacter(id)
    this.glowLayer.dispose()
    this.lastApplied = null
  }
}
