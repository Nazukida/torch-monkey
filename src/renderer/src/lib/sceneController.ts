import { BabylonEngine } from '@renderer/engine/BabylonEngine'
import { Stage3D } from '@renderer/stage/Stage3D'
import { Lighting } from '@renderer/stage/Lighting'
import { GlowstickVFX } from '@renderer/vfx/GlowstickVFX'
import { PostProcessingStack } from '@renderer/vfx/PostProcessing'
import { useStageStore } from '@renderer/stores/stageStore'
import { useCharacterStore } from '@renderer/stores/characterStore'
import { useTimelineStore } from '@renderer/stores/timelineStore'
import { usePlaybackStore } from '@renderer/stores/playbackStore'
import { useVfxStore } from '@renderer/stores/vfxStore'
import { useMotionStore } from '@renderer/stores/motionStore'
import type { MotionData } from '@shared/types/motion'
import type { MotionPlayer } from '@renderer/character/MotionPlayer'

/**
 * Wires the Zustand stores to the Babylon scene and owns the per-frame loop:
 * playback-time advance, per-character MotionPlayer driving, glowstick/trail
 * updates, and the kime bloom punch. Subscribes to config stores so panel edits
 * reflect immediately.
 */
class SceneControllerImpl {
  private stage: Stage3D | null = null
  private lighting: Lighting | null = null
  private vfx: GlowstickVFX | null = null
  private post: PostProcessingStack | null = null
  private disposeEngineCb: (() => void) | null = null
  private unsubs: Array<() => void> = []
  private motionCache = new Map<string, MotionData>()
  private lastKimeFrame = -1
  private started = false

  async init(canvas: HTMLCanvasElement): Promise<void> {
    await BabylonEngine.initialize(canvas)
    const scene = BabylonEngine.scene

    this.stage = new Stage3D(scene!, canvas, useStageStore.getState().config)
    this.lighting = new Lighting(scene!, useStageStore.getState().lightConfig)
    this.vfx = new GlowstickVFX(scene!)
    this.post = new PostProcessingStack(
      scene!,
      this.stage.getCamera(),
      useVfxStore.getState().config.postProcess
    )

    // Hand scene refs to the character store so addCharacter can build models.
    useCharacterStore.getState().init(scene!, this.lighting.getShadowGenerator(), this.vfx)
    // Build models for any characters created before the scene was ready.
    useCharacterStore.getState().reconcile()

    this.wireStores()
    this.disposeEngineCb = BabylonEngine.registerBeforeUpdate((delta) => void this.frame(delta))
    this.started = true
  }

  private wireStores(): void {
    this.unsubs.push(
      useStageStore.subscribe((s) => {
        if (!this.stage) return
        this.stage.updateSize(s.config.width, s.config.depth)
        this.stage.setFloorMode(s.config.floorMode)
        this.stage.setShowGrid(s.config.showGrid)
        this.stage.setFloorColor(s.config.floorColor)
        this.stage.setBackgroundColor(s.config.backgroundColor)
      })
    )
    this.unsubs.push(
      useStageStore.subscribe((s) => {
        this.lighting?.updateFromConfig(s.lightConfig)
      })
    )
    this.unsubs.push(
      useVfxStore.subscribe((s) => {
        this.post?.applyConfig(s.config.postProcess)
        this.vfx?.setTrailEnabled(s.config.glowstick.trail)
      })
    )
  }

  private async frame(delta: number): Promise<void> {
    if (!this.started) return
    const timeline = useTimelineStore.getState()
    const playback = usePlaybackStore.getState()

    playback.tick(delta, timeline.duration)

    const now = playback.currentTime
    const active = timeline.getClipsAtTime(now)

    for (const { trackId, clip } of active) {
      const track = timeline.tracks.find((t) => t.id === trackId)
      if (!track || track.type !== 'character' || !track.characterId) continue
      const player = useCharacterStore.getState().getPlayer(track.characterId)
      if (!player) continue
      await this.ensureMotion(player, clip.motionId)
      const motion = player.getMotion()
      if (!motion) continue
      const frame = timeline.getClipFrameAtTime(clip, now, motion.fps)
      if (frame !== null) player.seekToFrame(frame)
    }

    for (const model of useCharacterStore.getState().models.values()) {
      model.frameUpdate()
      this.vfx?.update(model)
    }

    this.maybeFireKime(now)
  }

  private maybeFireKime(now: number): void {
    if (usePlaybackStore.getState().status !== 'playing') return
    const clips = useTimelineStore.getState().getClipsAtTime(now)
    for (const { clip } of clips) {
      const motion = this.motionCache.get(clip.motionId)
      if (!motion) continue
      const fps = motion.fps
      const rel = now - clip.startTime
      const frame = Math.round(clip.motionStartFrame + rel * fps * (clip.speed || 1))
      for (const m of motion.beatMarkers) {
        if (m.type === 'kime' && m.frame === frame && frame !== this.lastKimeFrame) {
          this.lastKimeFrame = frame
          this.post?.triggerKimeEffect()
          this.vfx?.onKime()
        }
      }
    }
  }

  private async ensureMotion(player: MotionPlayer, motionId: string): Promise<void> {
    if (player.getMotion()?.id === motionId) return
    const cached = this.motionCache.get(motionId)
    if (cached) {
      player.loadMotion(cached)
      return
    }
    const data = await useMotionStore.getState().getMotionData(motionId)
    if (data) {
      this.motionCache.set(motionId, data)
      player.loadMotion(data)
    }
  }

  /** Invalidate cache when a motion is deleted/updated. */
  invalidateMotion(motionId: string): void {
    this.motionCache.delete(motionId)
  }

  dispose(): void {
    this.disposeEngineCb?.()
    this.disposeEngineCb = null
    this.unsubs.forEach((u) => u())
    this.unsubs = []
    this.stage?.dispose()
    this.lighting?.dispose()
    this.vfx?.dispose()
    this.post?.dispose()
    BabylonEngine.dispose()
    this.started = false
  }
}

export const SceneController = new SceneControllerImpl()
