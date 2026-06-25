import { useMotionStore } from '@renderer/stores/motionStore'
import type { BilibiliProcessOptions, BilibiliSource, BilibiliVideoInfo } from '@shared/types/electron'
import type { MotionData } from '@shared/types/motion'

/**
 * Probe a Bilibili video (BV 号 / BV id) without downloading — returns its
 * title / duration / uploader so the user can confirm before capturing.
 */
export async function probeBilibili(
  bvid: string,
  page?: number
): Promise<{ info?: BilibiliVideoInfo; error?: string }> {
  return window.electronAPI.previewBilibili(bvid, page)
}

/**
 * Download a Bilibili video by BV id and run it through the full AI mocap
 * pipeline (视频 → 2D → 3D → IK → 打艺优化 → MotionData). The resulting motion
 * is imported into the library with Bilibili provenance metadata.
 *
 * Responsibility: the caller (the user) is expected to have the rights to
 * download and analyse the chosen video. This captures ONE user-named video
 * for local motion analysis only.
 */
export async function captureFromBilibili(
  bvid: string,
  options?: BilibiliProcessOptions
): Promise<{ motion: MotionData; source?: BilibiliSource }> {
  const result = await window.electronAPI.processBilibili(bvid, options)

  if (result.status !== 'completed' || !result.motionData) {
    throw new Error(result.error ?? 'Bilibili capture failed')
  }

  const motion = result.motionData
  if (result.source) {
    // Use the real video title; tag with bilibili provenance.
    motion.name = result.source.title || motion.name
    motion.sourceVideoPath = result.source.url
    motion.tags = Array.from(
      new Set([...(motion.tags ?? []), 'bilibili', `BV:${result.source.bvid}`])
    )
  }

  await useMotionStore.getState().importMotion(motion)
  return { motion, source: result.source }
}
