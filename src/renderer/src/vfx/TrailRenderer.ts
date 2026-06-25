import {
  Scene,
  Mesh,
  VertexData,
  StandardMaterial,
  Color3,
  Color4,
  Vector3
} from '@babylonjs/core'

/**
 * Ribbon-based glowstick trail.
 *
 * Wotagei visual signatures, encoded as parameters:
 *  - High-speed motion → long afterimage (almost a full light circle).
 *  - A kime (hard stop) → trail collapses rapidly (see {@link clearRapidly}).
 *  - Trail fades from the glowstick color to transparent along its length.
 *
 * Lifetime scales with recent hand speed, clamped, so fast swings draw arcs and
 * holds draw nothing.
 */
export class TrailRenderer {
  private scene: Scene
  private color: Color3
  private points: Vector3[] = []
  private ribbon: Mesh | null = null
  private material: StandardMaterial

  private maxPoints = 180 // hard cap (~3s @ 60fps)
  private baseLifetimeSec = 0.5
  private speedScale = 0.05
  private ribbonWidth = 0.025 // ~ glowstick diameter
  private lastSpeed = 0
  private enabled = true

  constructor(scene: Scene, color: Color3) {
    this.scene = scene
    this.color = color
    this.material = new StandardMaterial('trailMat', scene)
    this.material.emissiveColor = color
    this.material.diffuseColor = Color3.Black()
    this.material.specularColor = Color3.Black()
    this.material.alpha = 0.9
    this.material.backFaceCulling = false
    this.material.disableLighting = true
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled
    if (!enabled) this.points = []
    this.ribbon?.setEnabled(enabled)
  }

  setColor(color: Color3): void {
    this.color = color
    this.material.emissiveColor = color
  }

  addPoint(position: Vector3): void {
    if (!this.enabled) return
    this.points.push(position.clone())

    this.lastSpeed = this.calculateSpeed()
    const dynamicLifetime = this.baseLifetimeSec + this.lastSpeed * this.speedScale
    const maxFrames = Math.min(Math.floor(dynamicLifetime * 60), this.maxPoints)

    while (this.points.length > maxFrames) this.points.shift()
    if (this.points.length > 1) this.rebuildRibbon()
  }

  private calculateSpeed(): number {
    if (this.points.length < 2) return 0
    const last = this.points[this.points.length - 1]
    const prev = this.points[this.points.length - 2]
    return Vector3.Distance(last, prev) * 60 // m/s assuming 60fps ticks
  }

  getLastSpeed(): number {
    return this.lastSpeed
  }

  private rebuildRibbon(): void {
    const path = this.points
    const n = path.length
    if (n < 2) return

    if (this.ribbon) {
      this.ribbon.dispose()
    }

    const positions: number[] = []
    const colors: number[] = []
    const indices: number[] = []
    const up = Vector3.Up()

    for (let i = 0; i < n; i++) {
      const p = path[i]
      // Tangent via neighbor difference (handles single-segment ends).
      const prev = path[Math.max(0, i - 1)]
      const next = path[Math.min(n - 1, i + 1)]
      const dir = next.subtract(prev)
      if (dir.lengthSquared() < 1e-8) dir.copyFrom(up)
      else dir.normalize()

      let perp = Vector3.Cross(dir, up)
      if (perp.lengthSquared() < 1e-6) perp = Vector3.Cross(dir, Vector3.Right())
      perp.normalize().scaleInPlace(this.ribbonWidth / 2)

      // Fade: newest (i = n-1) opaque, oldest (i = 0) transparent.
      const alphaN = i / (n - 1)
      const fade = alphaN * alphaN

      const v0 = p.add(perp)
      const v1 = p.subtract(perp)
      positions.push(v0.x, v0.y, v0.z, v1.x, v1.y, v1.z)
      colors.push(
        this.color.r,
        this.color.g,
        this.color.b,
        fade,
        this.color.r,
        this.color.g,
        this.color.b,
        fade
      )
    }

    for (let i = 0; i < n - 1; i++) {
      const a = i * 2
      const b = a + 1
      const c = a + 2
      const d = a + 3
      indices.push(a, b, c, b, d, c)
    }

    const vd = new VertexData()
    vd.positions = positions
    vd.colors = colors
    vd.indices = indices

    const ribbon = new Mesh('trailRibbon', this.scene)
    vd.applyToMesh(ribbon)
    ribbon.material = this.material
    ribbon.hasVertexAlpha = true
    ribbon.isPickable = false
    ribbon.alwaysSelectAsActiveMesh = true // keep trails alive when off-screen
    this.ribbon = ribbon
  }

  /** Kime: collapse the trail to a tiny stub near-instantly. */
  clearRapidly(): void {
    this.points = this.points.slice(-3)
    if (this.points.length > 1) this.rebuildRibbon()
    else this.ribbon?.setEnabled(false)
  }

  clear(): void {
    this.points = []
    this.ribbon?.setEnabled(false)
  }

  dispose(): void {
    this.ribbon?.dispose()
    this.material.dispose()
    this.points = []
  }
}
