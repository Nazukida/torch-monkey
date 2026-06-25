import { useRef, useState } from 'react'
import { TransportBar } from './TransportBar'
import { useTimelineStore } from '@renderer/stores/timelineStore'
import { usePlaybackStore } from '@renderer/stores/playbackStore'
import { useCharacterStore } from '@renderer/stores/characterStore'
import type { TimelineClip, TimelineTrack } from '@shared/types/timeline'

const LANE_HEIGHT = 44
const GUTTER_WIDTH = 140

interface DroppedMotionPayload {
  motionId: string
  motionName: string
  duration: number
  frameCount: number
  fps: number
}

export function TimelineContainer(): React.JSX.Element {
  const tracks = useTimelineStore((s) => s.tracks)
  const duration = useTimelineStore((s) => s.duration)
  const currentTime = usePlaybackStore((s) => s.currentTime)
  const [pps, setPps] = useState(40)
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const totalWidth = Math.max(800, duration * pps + 100)

  return (
    <div className="flex h-64 flex-col border-t border-zinc-800 bg-zinc-900/70">
      <TransportBar />
      <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-1 text-xs text-zinc-400">
        <span>缩放</span>
        <input
          type="range"
          className="w-32"
          min={10}
          max={160}
          step={1}
          value={pps}
          onChange={(e) => setPps(parseInt(e.target.value))}
        />
        <span className="mr-3">{pps}px/s</span>
        <button
          className="rounded bg-zinc-800 px-2 py-0.5 hover:bg-zinc-700"
          onClick={() => useTimelineStore.getState().setDuration(duration + 10)}
        >
          +10s
        </button>
        <span className="ml-auto text-zinc-500">
          {tracks.length} 轨道 · 拖拽动作到角色轨道
        </span>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
        <div style={{ width: GUTTER_WIDTH + totalWidth }}>
          <Ruler duration={duration} pps={pps} currentTime={currentTime} />
          {tracks.map((track) => (
            <TrackLane
              key={track.id}
              track={track}
              pps={pps}
              width={totalWidth}
              selectedClipId={selectedClipId}
              onSelectClip={setSelectedClipId}
            />
          ))}
          <WaveformLane duration={duration} pps={pps} width={totalWidth} currentTime={currentTime} />
        </div>
      </div>
    </div>
  )
}

function Ruler({
  duration,
  pps,
  currentTime
}: {
  duration: number
  pps: number
  currentTime: number
}): React.JSX.Element {
  const ticks: React.JSX.Element[] = []
  const step = pps < 25 ? 5 : pps < 60 ? 2 : 1
  for (let s = 0; s <= duration; s += step) {
    ticks.push(
      <div
        key={s}
        className="absolute top-0 flex h-full flex-col justify-end text-[10px] text-zinc-500"
        style={{ left: GUTTER_WIDTH + s * pps }}
      >
        <span className="ml-1">{s}s</span>
      </div>
    )
  }
  return (
    <div
      className="relative border-b border-zinc-800 bg-zinc-900"
      style={{ height: 18, marginLeft: GUTTER_WIDTH }}
    >
      {ticks}
      <Playhead left={GUTTER_WIDTH + currentTime * pps} />
    </div>
  )
}

function Playhead({ left }: { left: number }): React.JSX.Element {
  return (
    <div
      className="pointer-events-none absolute top-0 z-20 h-full w-px bg-red-500"
      style={{ left }}
    >
      <div className="absolute -left-1.5 -top-0 h-3 w-3 rounded-b-sm bg-red-500" />
    </div>
  )
}

function TrackLane({
  track,
  pps,
  width,
  selectedClipId,
  onSelectClip
}: {
  track: TimelineTrack
  pps: number
  width: number
  selectedClipId: string | null
  onSelectClip: (id: string | null) => void
}): React.JSX.Element {
  const onDrop = (e: React.DragEvent): void => {
    e.preventDefault()
    const raw = e.dataTransfer.getData('application/x-torchmonkey-motion')
    if (!raw) return
    const payload = JSON.parse(raw) as DroppedMotionPayload
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const startTime = Math.max(0, (e.clientX - rect.left) / pps)
    useTimelineStore
      .getState()
      .addClipFromMotion(
        track.id,
        payload.motionId,
        payload.motionName,
        startTime,
        payload.duration,
        payload.frameCount,
        payload.fps
      )
  }

  return (
    <div className="flex border-b border-zinc-800/60">
      <div
        className="flex shrink-0 items-center gap-1 px-2 text-xs"
        style={{ width: GUTTER_WIDTH, height: LANE_HEIGHT, color: track.color }}
      >
        <button
          className="text-zinc-500 hover:text-zinc-200"
          title={track.locked ? '解锁' : '锁定'}
          onClick={() => useTimelineStore.getState().toggleLock(track.id)}
        >
          {track.locked ? '🔒' : '🔓'}
        </button>
        <button
          className="text-zinc-500 hover:text-zinc-200"
          title={track.muted ? '取消静音' : '静音'}
          onClick={() => useTimelineStore.getState().toggleMute(track.id)}
        >
          {track.muted ? '🔇' : '🔊'}
        </button>
        <span className="truncate text-zinc-300">{track.label}</span>
      </div>
      <div
        className="relative"
        style={{ width, height: LANE_HEIGHT }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        onPointerDown={(e) => {
          // Click empty lane area → scrub.
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
          const t = (e.clientX - rect.left) / pps
          usePlaybackStore.getState().seek(t, useTimelineStore.getState().duration)
        }}
      >
        {track.clips.map((clip) => (
          <ClipBlock
            key={clip.id}
            clip={clip}
            pps={pps}
            color={track.color}
            selected={selectedClipId === clip.id}
            trackId={track.id}
            locked={track.locked}
            onSelect={onSelectClip}
          />
        ))}
      </div>
    </div>
  )
}

function ClipBlock({
  clip,
  pps,
  color,
  selected,
  trackId,
  locked,
  onSelect
}: {
  clip: TimelineClip
  pps: number
  color: string
  selected: boolean
  trackId: string
  locked: boolean
  onSelect: (id: string | null) => void
}): React.JSX.Element {
  const left = clip.startTime * pps
  const width = Math.max(8, clip.duration * pps)
  const [drag, setDrag] = useState<null | { mode: 'move' | 'l' | 'r'; startX: number; base: number }>(null)

  const onPointerDown = (e: React.PointerEvent, mode: 'move' | 'l' | 'r'): void => {
    if (locked) return
    e.stopPropagation()
    onSelect(clip.id)
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    setDrag({ mode, startX: e.clientX, base: mode === 'move' ? clip.startTime : clip.duration })
  }

  const onPointerMove = (e: React.PointerEvent): void => {
    if (!drag) return
    const dx = (e.clientX - drag.startX) / pps
    const store = useTimelineStore.getState()
    if (drag.mode === 'move') {
      store.moveClip(clip.id, Math.max(0, drag.base + dx))
    } else if (drag.mode === 'l') {
      const newStart = Math.max(0, clip.startTime + dx)
      const newDur = Math.max(0.1, clip.duration - dx)
      store.trimClip(clip.id, newStart, newStart + newDur)
    } else {
      store.trimClip(clip.id, clip.startTime, clip.startTime + Math.max(0.1, drag.base + dx))
    }
  }

  const onPointerUp = (e: React.PointerEvent): void => {
    if (drag) {
      ;(e.target as HTMLElement).releasePointerCapture(e.pointerId)
      setDrag(null)
    }
  }

  return (
    <div
      className={`absolute top-1 flex cursor-grab items-center rounded px-1.5 text-[10px] text-white ${
        selected ? 'ring-2 ring-white' : ''
      } ${locked ? 'opacity-60' : ''}`}
      style={{ left, width, height: LANE_HEIGHT - 8, backgroundColor: color }}
      onPointerDown={(e) => onPointerDown(e, 'move')}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      title={`${clip.motionName} · ${clip.duration.toFixed(2)}s`}
    >
      <span className="truncate">{clip.motionName}</span>
      {!locked && (
        <>
          <span
            className="absolute left-0 top-0 h-full w-1.5 cursor-ew-resize bg-black/30"
            onPointerDown={(e) => onPointerDown(e, 'l')}
          />
          <span
            className="absolute right-0 top-0 h-full w-1.5 cursor-ew-resize bg-black/30"
            onPointerDown={(e) => onPointerDown(e, 'r')}
          />
        </>
      )}
      {selected && (
        <span
          className="absolute -right-12 top-0 flex h-full items-center text-zinc-300"
          onClick={(e) => {
            e.stopPropagation()
            useTimelineStore.getState().removeClip(clip.id)
            onSelect(null)
            void trackId
          }}
        >
          <button className="rounded bg-red-600 px-1 text-[9px]">删除</button>
        </span>
      )}
    </div>
  )
}

function WaveformLane({
  duration,
  pps,
  width,
  currentTime
}: {
  duration: number
  pps: number
  width: number
  currentTime: number
}): React.JSX.Element {
  const audioName = usePlaybackStore((s) => s.audioName)
  const beats = useTimelineStore((s) => s.beatMarkers)
  const [peaks, setPeaks] = useState<number[]>([])

  // Re-derive peaks when the audio changes (cheap; cached on the store).
  const buffer = usePlaybackStore.getState().audioBuffer
  void (
    buffer &&
    peaks.length === 0 &&
    setPeaks(computePeaksCached(buffer, Math.floor(width)))
  )

  return (
    <div className="flex border-b border-zinc-800/60 bg-zinc-950/50">
      <div className="flex shrink-0 items-center px-2 text-xs text-zinc-500" style={{ width: GUTTER_WIDTH, height: 48 }}>
        🎵 波形
      </div>
      <div className="relative" style={{ width, height: 48 }}>
        {audioName && peaks.length > 0 ? (
          <svg className="absolute inset-0" width={width} height={48} preserveAspectRatio="none">
            {peaks.map((p, i) => {
              const h = Math.max(1, p * 40)
              return (
                <rect
                  key={i}
                  x={(i / peaks.length) * width}
                  y={24 - h}
                  width={Math.max(1, width / peaks.length)}
                  height={h * 2}
                  fill="#3f6212"
                />
              )
            })}
          </svg>
        ) : (
          <div className="flex h-full items-center justify-center text-[10px] text-zinc-600">
            导入音频后显示波形
          </div>
        )}
        {beats.map((b, i) => {
          const t = b.frame / 30
          if (t > duration) return null
          return (
            <div
              key={i}
              className="absolute top-0 h-full w-px bg-fuchsia-400/70"
              style={{ left: t * pps }}
              title={b.label}
            />
          )
        })}
        <Playhead left={currentTime * pps} />
      </div>
    </div>
  )
}

let _lastBuf: AudioBuffer | null = null
let _lastPeaks: number[] = []
function computePeaksCached(buffer: AudioBuffer, n: number): number[] {
  if (_lastBuf === buffer && _lastPeaks.length) return _lastPeaks
  const ch = buffer.getChannelData(0)
  const block = Math.max(1, Math.floor(ch.length / n))
  const out: number[] = []
  let max = 0.0001
  for (let i = 0; i < n; i++) {
    let peak = 0
    for (let j = 0; j < block; j++) {
      const v = Math.abs(ch[i * block + j] ?? 0)
      if (v > peak) peak = v
    }
    out.push(peak)
    if (peak > max) max = peak
  }
  _lastBuf = buffer
  _lastPeaks = out.map((p) => p / max)
  return _lastPeaks
}
