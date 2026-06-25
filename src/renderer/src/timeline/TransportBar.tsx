import { useState } from 'react'
import { usePlaybackStore } from '@renderer/stores/playbackStore'
import { useTimelineStore } from '@renderer/stores/timelineStore'
import { loadAudioFile, computePeaks } from '@renderer/lib/audioLoader'
import type { BeatMarker } from '@shared/types/motion'

function fmt(t: number): string {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  const ms = Math.floor((t - Math.floor(t)) * 1000)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
}

export function TransportBar(): React.JSX.Element {
  const status = usePlaybackStore((s) => s.status)
  const currentTime = usePlaybackStore((s) => s.currentTime)
  const speed = usePlaybackStore((s) => s.speed)
  const duration = useTimelineStore((s) => s.duration)
  const audioName = usePlaybackStore((s) => s.audioName)
  const [busy, setBusy] = useState(false)

  const pb = usePlaybackStore.getState()
  const tl = useTimelineStore.getState()

  return (
    <div className="flex h-10 items-center gap-2 border-b border-zinc-800 bg-zinc-900 px-3 text-sm">
      <button
        className="rounded bg-zinc-800 px-2 py-1 hover:bg-zinc-700"
        onClick={() => pb.stop()}
        title="停止"
      >
        ⏹
      </button>
      <button
        className="rounded bg-zinc-800 px-2 py-1 hover:bg-zinc-700"
        onClick={() => (status === 'playing' ? pb.pause() : pb.play(duration))}
        title="播放/暂停 (Space)"
      >
        {status === 'playing' ? '⏸' : '▶'}
      </button>
      <div className="font-mono text-xs text-zinc-300">
        {fmt(currentTime)} / {fmt(duration)}
      </div>

      <div className="mx-2 flex items-center gap-1 text-xs text-zinc-400">
        <span>速度</span>
        <input
          type="range"
          className="w-20"
          min={0.25}
          max={2}
          step={0.05}
          value={speed}
          onChange={(e) => pb.setSpeed(parseFloat(e.target.value))}
        />
        <span className="w-8 text-zinc-300">{speed.toFixed(2)}x</span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <span className="max-w-[12rem] truncate text-xs text-zinc-500">
          {audioName ? `🎵 ${audioName}` : '无音频'}
        </span>
        <button
          className="rounded bg-zinc-800 px-2 py-1 text-xs hover:bg-zinc-700"
          disabled={busy}
          onClick={async () => {
            const picked = await window.electronAPI.openFileDialog({
              title: '导入音频',
              filters: [
                { name: 'Audio', extensions: ['mp3', 'wav', 'ogg', 'm4a', 'flac'] }
              ]
            })
            if (picked.canceled || picked.filePaths.length === 0) return
            setBusy(true)
            try {
              await loadAudioFile(picked.filePaths[0])
            } catch (e) {
              alert(`音频加载失败: ${(e as Error).message}`)
            } finally {
              setBusy(false)
            }
          }}
        >
          🎵 导入音频
        </button>
        <button
          className="rounded bg-zinc-800 px-2 py-1 text-xs hover:bg-zinc-700"
          onClick={() => detectBeatsFromPlayback()}
          title="基于波形峰值粗略打点"
        >
          🥁 节拍检测
        </button>
      </div>
    </div>
  )
}

/** Naive onset detection from the loaded audio's channel-0 peaks. */
function detectBeatsFromPlayback(): void {
  const buffer = usePlaybackStore.getState().audioBuffer
  if (!buffer) {
    alert('请先导入音频')
    return
  }
  const peaks = computePeaks(buffer, Math.floor(buffer.sampleRate * buffer.duration))
  const threshold = 0.5
  const beats: BeatMarker[] = []
  let lastBeatFrame = -44100
  const samplesPerFrame = Math.max(1, Math.floor(buffer.length / peaks.length))
  for (let i = 0; i < peaks.length; i++) {
    if (peaks[i] > threshold && i - lastBeatFrame > Math.floor(0.25 * peaks.length / Math.max(1, buffer.duration))) {
      const time = (i * samplesPerFrame) / buffer.sampleRate
      beats.push({ frame: Math.round(time * 30), beat: '', type: 'downbeat', label: `beat ${beats.length + 1}` })
      lastBeatFrame = i
    }
  }
  useTimelineStore.getState().setBeatMarkers(beats)
}
