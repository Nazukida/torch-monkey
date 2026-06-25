import {
  Scene,
  Mesh,
  MeshBuilder,
  ArcRotateCamera,
  Vector3,
  Color3,
  Color4,
  StandardMaterial,
  ShadowGenerator,
  DirectionalLight,
  Texture
} from '@babylonjs/core'
import { GridMaterial } from '@babylonjs/materials'
import type { StageConfig, FloorMode } from '@shared/types/stage'

function hexToColor4(hex: string): Color4 {
  const m = hex.replace('#', '')
  const r = parseInt(m.substring(0, 2), 16) / 255
  const g = parseInt(m.substring(2, 4), 16) / 255
  const b = parseInt(m.substring(4, 6), 16) / 255
  return new Color4(r, g, b, 1)
}
function hexToColor3(hex: string): Color3 {
  const c = hexToColor4(hex)
  return new Color3(c.r, c.g, c.b)
}

/**
 * The 3D stage: floor (+ reference grid), and an orbit camera.
 * Lighting lives in {@link Lighting}; together they sell the dark-venue look.
 */
export class Stage3D {
  private scene: Scene
  private canvas: HTMLCanvasElement
  private floor: Mesh | null = null
  private reflectiveFloor: Mesh | null = null
  private gridMat: GridMaterial | null = null
  private solidMat: StandardMaterial | null = null
  private camera: ArcRotateCamera
  private config: StageConfig

  constructor(scene: Scene, canvas: HTMLCanvasElement, config: StageConfig) {
    this.scene = scene
    this.canvas = canvas
    this.config = config
    this.camera = this.setupCamera()
    this.createStage(config)
  }

  private setupCamera(): ArcRotateCamera {
    const camera = new ArcRotateCamera(
      'mainCamera',
      -Math.PI / 4, // alpha (horizontal)
      Math.PI / 3, // beta (vertical, 60°)
      15, // radius
      Vector3.Zero(),
      this.scene
    )
    camera.lowerRadiusLimit = 3
    camera.upperRadiusLimit = 50
    camera.lowerBetaLimit = 0.1
    camera.upperBetaLimit = Math.PI / 2 - 0.05
    camera.minZ = 0.1
    camera.inertia = 0.85
    camera.panningInertia = 0.5
    camera.wheelPrecision = 12
    camera.attachControl(this.canvas, true)
    return camera
  }

  getCamera(): ArcRotateCamera {
    return this.camera
  }

  private createStage(config: StageConfig): void {
    this.config = config
    this.scene.clearColor = hexToColor4(config.backgroundColor)

    this.floor = MeshBuilder.CreateGround(
      'stageFloor',
      { width: config.width, height: config.depth, subdivisions: 2 },
      this.scene
    )
    this.floor.receiveShadows = true

    // Grid material (reference grid for spatial awareness)
    this.gridMat = new GridMaterial('stageGrid', this.scene)
    this.gridMat.majorUnitFrequency = 1
    this.gridMat.minorUnitVisibility = 0.3
    this.gridMat.gridRatio = 1
    this.gridMat.mainColor = new Color3(0.15, 0.15, 0.2)
    this.gridMat.lineColor = new Color3(0.3, 0.3, 0.5)
    this.gridMat.opacity = 0.6

    // Solid material fallback
    this.solidMat = new StandardMaterial('stageSolid', this.scene)
    this.solidMat.diffuseColor = hexToColor3(config.floorColor)
    this.solidMat.specularColor = new Color3(0.05, 0.05, 0.08)

    this.applyFloorMode()
  }

  private applyFloorMode(): void {
    if (!this.floor || !this.gridMat || !this.solidMat) return
    switch (this.config.floorMode) {
      case 'grid':
        this.floor.material = this.gridMat
        this.gridMat.opacity = this.config.showGrid ? 0.6 : 0.15
        break
      case 'solid':
        this.floor.material = this.solidMat
        break
      case 'reflective':
        // Mirror-like dark floor: cheap fake via a high-specular dark material.
        this.solidMat.specularColor = new Color3(0.4, 0.4, 0.5)
        this.solidMat.specularPower = 256
        this.floor.material = this.solidMat
        break
    }
  }

  updateSize(width: number, depth: number): void {
    this.config.width = width
    this.config.depth = depth
    // Rebuild the ground mesh at the new size.
    this.floor?.dispose()
    this.floor = MeshBuilder.CreateGround(
      'stageFloor',
      { width, height: depth, subdivisions: 2 },
      this.scene
    )
    this.floor.receiveShadows = true
    this.applyFloorMode()
  }

  setFloorMode(mode: FloorMode): void {
    this.config.floorMode = mode
    if (mode === 'reflective' && !this.reflectiveFloor) {
      // No persistent reflective mesh in the cheap variant; applyFloorMode handles look.
    }
    this.applyFloorMode()
  }

  setShowGrid(show: boolean): void {
    this.config.showGrid = show
    this.applyFloorMode()
  }

  setFloorColor(hex: string): void {
    this.config.floorColor = hex
    if (this.solidMat) this.solidMat.diffuseColor = hexToColor3(hex)
  }

  setBackgroundColor(hex: string): void {
    this.config.backgroundColor = hex
    this.scene.clearColor = hexToColor4(hex)
  }

  getConfig(): StageConfig {
    return this.config
  }

  dispose(): void {
    this.floor?.dispose()
    this.reflectiveFloor?.dispose()
    this.gridMat?.dispose()
    this.solidMat?.dispose()
    this.camera.dispose()
  }
}

/**
 * Small helper for modules that need a usable texture-free default checker;
 * kept here to centralize asset-free defaults.
 */
export function makeFloorTexture(scene: Scene): Texture | null {
  return null
}

/** Reserved: shadow generators are owned by Lighting, but Stage exposes the floor. */
export type StageShadowSetup = { generator: ShadowGenerator; light: DirectionalLight }
