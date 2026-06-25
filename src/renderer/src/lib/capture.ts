import { useMotionStore } from '@renderer/stores/motionStore'
import type { MotionData } from '@shared/types/motion'

/**
 * Pick a video file via the OS dialog and run it through the Python AI pipeline.
 * On success the resulting {@link MotionData} is inserted into the library and
 * returned so the caller can (optionally) drop it onto a timeline track.
 */
export async function importVideoForCapture(): Promise<MotionData | null> {
  const picked = await window.electronAPI.openFileDialog({
    title: 'Import Wota-艺 video for AI capture',
    filters: [{ name: 'Video', extensions: ['mp4', 'mov', 'avi', 'mkv', 'webm'] }]
  })
  if (picked.canceled || picked.filePaths.length === 0) return null
  const filePath = picked.filePaths[0]

  const result = await window.electronAPI.processVideo(filePath, {
    fps: 30,
    smooth: true,
    detectKime: true
  })

  if (result.status !== 'completed' || !result.motionData) {
    throw new Error(result.error ?? 'Capture failed')
  }

  await useMotionStore.getState().importMotion(result.motionData)
  return result.motionData
}
