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
import type { GlowstickConfig } from '@shared/types/vfx'
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
  /** Last-applied glowstick config ref — skips applyGlowConfig when unchanged. */
  private lastGlow: GlowstickConfig | null = null
  /**
   * Idempotent init + ref-counted teardown. React 19 StrictMode double-invokes
   * effects (setup1 → cleanup1 → setup2) in dev, so a naive "init on mount /
   * dispose on cleanup" singleton tears itself down during cleanup1 and leaves
   * the second mount pointing at a disposed scene — every panel edit then looks
   * dead. We (a) run the real init exactly once (initPromise guards re-entry)
   * and (b) ref-count owners with a deferred teardown: release() only *schedules*
   * a dispose, and a subsequent init() cancels it, so StrictMode's immediate
   * remount keeps the scene alive while a true unmount still tears it down.
   */
  private initPromise: Promise<void> | null = null
  private owners = 0
  private disposeTimer: ReturnType<typeof setTimeout> | null = null

  init(canvas: HTMLCanvasElement): Promise<void> {
    this.owners++
    if (this.disposeTimer) {
      clearTimeout(this.disposeTimer)
      this.disposeTimer = null
    }
    if (this.initPromise) return this.initPromise
    this.initPromise = this.doInit(canvas)
    return this.initPromise
  }

  private async doInit(canvas: HTMLCanvasElement): Promise<void> {
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
        const glow = s.config.glowstick
        this.vfx?.setTrailEnabled(glow.trail)
        // Push the rest of the glowstick config (enabled/doubleWield/colors/
        // intensity/light) onto the scene — only when the glow ref actually
        // changed, so post-process slider drags don't re-apply glowsticks.
        if (glow !== this.lastGlow) {
          this.lastGlow = glow
          this.vfx?.applyGlowConfig(glow, useCharacterStore.getState().models.entries())
        }
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

  /**
   * Release one owner. The scene is torn down only when the last owner is gone
   * AND no new init() arrives before the deferred teardown fires — which is what
   * keeps the scene alive across StrictMode's setup→cleanup→setup sequence.
   */
  release(): void {
    this.owners = Math.max(0, this.owners - 1)
    if (this.owners === 0 && this.initPromise && !this.disposeTimer) {
      this.disposeTimer = setTimeout(() => {
        this.disposeTimer = null
        this.dispose()
      }, 0)
    }
  }

  dispose(): void {
    if (this.disposeTimer) {
      clearTimeout(this.disposeTimer)
      this.disposeTimer = null
    }
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
    this.initPromise = null
    this.owners = 0
  }
}

export const SceneController = new SceneControllerImpl()
