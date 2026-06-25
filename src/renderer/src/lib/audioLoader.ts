import { usePlaybackStore } from '@renderer/stores/playbackStore'
import { useTimelineStore } from '@renderer/stores/timelineStore'

let audioCtx: AudioContext | null = null
function getCtx(): AudioContext {
  if (!audioCtx) {
    audioCtx = new AudioContext()
  }
  return audioCtx
}

/**
 * Read an audio file through the main process and decode it via the Web Audio
 * API. The decoded buffer feeds both playback and the timeline waveform.
 */
export async function loadAudioFile(
  filePath: string
): Promise<{ peaks: number[]; duration: number; error?: string }> {
  try {
    const { data, error } = await window.electronAPI.readFile(filePath)
    if (error || !data) return { peaks: [], duration: 0, error: error ?? 'read failed' }

    const ctx = getCtx()
    const audioBuffer = await ctx.decodeAudioData(data.slice(0))
    usePlaybackStore.getState().loadAudio(audioBuffer, filePath)
    useTimelineStore.getState().setAudio(filePath, audioBuffer.duration)
    useTimelineStore.getState().setDuration(
      Math.max(useTimelineStore.getState().duration, audioBuffer.duration)
    )

    const peaks = computePeaks(audioBuffer, 2000)
    return { peaks, duration: audioBuffer.duration }
  } catch (e) {
    return { peaks: [], duration: 0, error: (e as Error).message }
  }
}

/** Downsample channel 0 into N peak amplitudes for the waveform view. */
export function computePeaks(buffer: AudioBuffer, buckets: number): number[] {
  const channel = buffer.getChannelData(0)
  const blockSize = Math.max(1, Math.floor(channel.length / buckets))
  const peaks: number[] = []
  let max = 0.0001
  for (let i = 0; i < buckets; i++) {
    const start = i * blockSize
    let peak = 0
    for (let j = 0; j < blockSize && start + j < channel.length; j++) {
      const v = Math.abs(channel[start + j])
      if (v > peak) peak = v
    }
    peaks.push(peak)
    if (peak > max) max = peak
  }
  // Normalize to 0..1.
  return peaks.map((p) => p / max)
}
