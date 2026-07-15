import { useRef, useState } from 'react'
import { TransportBar } from './TransportBar'
import { useTimelineStore } from '@renderer/stores/timelineStore'
import { usePlaybackStore } from '@renderer/stores/playbackStore'
import { useUiStore } from '@renderer/stores/uiStore'
import { snapTime, type SnapContext } from './snap'
import type { TimelineClip, TimelineTrack } from '@shared/types/timeline'

const LANE_HEIGHT = 44
const GUTTER_WIDTH = 140
const MOTION_MIME = 'application/x-torchmonkey-motion'

interface DroppedMotionPayload {
  motionId: string
  motionName: string
  duration: number
  frameCount: number
  fps: number
}

/**
 * Build the snap context for the clip being dragged/dropped. Threshold is 0 when
 * snap is disabled, so {@link snapTime} becomes a pass-through. Clips are gathered
 * across ALL tracks so performers can align to the same beat/edge as neighbours.
 */
function buildSnapContext(activeClipId: string): SnapContext {
  const tl = useTimelineStore.getState()
  return {
    activeClipId,
    clips: tl.tracks.flatMap((t) => t.clips),
    playhead: usePlaybackStore.getState().currentTime,
    origin: 0,
    threshold: tl.snapEnabled ? tl.snapThreshold : 0
  }
}

/** Map a pointer client X to a timeline time (seconds) using the element's own
 *  left edge — works for both the ruler and the lane body since each already
 *  starts at the post-gutter origin. */
function seekToX(clientX: number, el: Element, pps: number, duration: number): void {
  const rect = el.getBoundingClientRect()
  const t = Math.max(0, Math.min((clientX - rect.left) / pps, duration))
  usePlaybackStore.getState().seek(t, duration)
}

export function TimelineContainer(): React.JSX.Element {
  const tracks = useTimelineStore((s) => s.tracks)
  const duration = useTimelineStore((s) => s.duration)
  const snapEnabled = useTimelineStore((s) => s.snapEnabled)
  const currentTime = usePlaybackStore((s) => s.currentTime)
  const [pps, setPps] = useState(40)
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null)
  const [panelHeight, setPanelHeight] = useState(256)
  const scrollRef = useRef<HTMLDivElement>(null)

  const totalWidth = Math.max(800, duration * pps + 100)

  // ---- Panel height resize (top edge) ----
  const resizeDrag = useRef<null | { startY: number; startH: number }>(null)
  const onResizeDown = (e: React.PointerEvent): void => {
    e.currentTarget.setPointerCapture(e.pointerId)
    resizeDrag.current = { startY: e.clientY, startH: panelHeight }
  }
  const onResizeMove = (e: React.PointerEvent): void => {
    if (!resizeDrag.current) return
    const dy = e.clientY - resizeDrag.current.startY
    // Dragging the top edge UP (dy<0) grows the panel.
    const next = Math.max(
      140,
      Math.min(resizeDrag.current.startH - dy, Math.round(window.innerHeight * 0.85))
    )
    setPanelHeight(next)
  }
  const onResizeUp = (e: React.PointerEvent): void => {
    if (resizeDrag.current) {
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        /* already released */
      }
      resizeDrag.current = null
    }
  }

  return (
    <div
      className="flex flex-col border-t border-zinc-800 bg-zinc-900/70"
      style={{ height: panelHeight }}
    >
      <div
        className="h-1 w-full shrink-0 cursor-rows-resize bg-zinc-800 hover:bg-blue-500"
        title="拖动调整时间线高度"
        onPointerDown={onResizeDown}
        onPointerMove={onResizeMove}
        onPointerUp={onResizeUp}
      />
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
        <button
          className={`rounded px-2 py-0.5 ${
            snapEnabled ? 'bg-blue-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
          }`}
          title="磁吸：拖拽时动作自动吸附到相邻动作边缘 / 播放头 / 起点"
          onClick={() => useTimelineStore.getState().toggleSnap()}
        >
          🧲 磁吸
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
              duration={duration}
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
  const scrubbing = useRef(false)

  // The ruler element is already offset by marginLeft = GUTTER_WIDTH, so its
  // internal coordinate origin is the post-gutter edge: a tick at second `s`
  // sits at left = s*pps (NOT GUTTER + s*pps — that double-offset was the old
  // bug that left the labels + playhead 140px to the right of the clips).
  const ticks: React.JSX.Element[] = []
  const step = pps < 25 ? 5 : pps < 60 ? 2 : 1
  for (let s = 0; s <= duration; s += step) {
    ticks.push(
      <div
        key={s}
        className="absolute top-0 flex h-full flex-col justify-end text-[10px] text-zinc-500"
        style={{ left: s * pps }}
      >
        <span className="ml-1">{s}s</span>
      </div>
    )
  }

  const onDown = (e: React.PointerEvent): void => {
    e.currentTarget.setPointerCapture(e.pointerId)
    scrubbing.current = true
    seekToX(e.clientX, e.currentTarget, pps, duration)
  }
  const onMove = (e: React.PointerEvent): void => {
    if (!scrubbing.current) return
    seekToX(e.clientX, e.currentTarget, pps, duration)
  }
  const onUp = (e: React.PointerEvent): void => {
    scrubbing.current = false
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }

  return (
    <div
      className="relative cursor-pointer border-b border-zinc-800 bg-zinc-900"
      style={{ height: 18, marginLeft: GUTTER_WIDTH, touchAction: 'none' }}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
    >
      {ticks}
      <Playhead left={currentTime * pps} />
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
  duration,
  selectedClipId,
  onSelectClip
}: {
  track: TimelineTrack
  pps: number
  width: number
  duration: number
  selectedClipId: string | null
  onSelectClip: (id: string | null) => void
}): React.JSX.Element {
  const motionDragActive = useUiStore((s) => s.motionDragActive)
  const canDropMotion = track.type === 'character' && !track.locked
  const [dragDepth, setDragDepth] = useState(0)
  const [caretX, setCaretX] = useState<number | null>(null)
  const isHover = dragDepth > 0
  const scrubbing = useRef(false)

  const accepts = (e: React.DragEvent): boolean =>
    canDropMotion && Array.from(e.dataTransfer.types).includes(MOTION_MIME)

  const onDragEnter = (e: React.DragEvent): void => {
    if (!accepts(e)) return // leave the native no-drop cursor on ineligible lanes
    e.preventDefault()
    setDragDepth((d) => d + 1)
  }
  const onDragOver = (e: React.DragEvent): void => {
    if (!accepts(e)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const rawX = Math.max(0, e.clientX - rect.left)
    // Snap the caret preview so it shows where the clip will actually land.
    const snapped = snapTime(rawX / pps, buildSnapContext('__new__'))
    setCaretX(snapped.matchedTarget !== null ? snapped.time * pps : rawX)
  }
  const onDragLeave = (): void => {
    setDragDepth((d) => {
      const next = Math.max(0, d - 1)
      if (next === 0) setCaretX(null)
      return next
    })
  }
  const onDrop = (e: React.DragEvent): void => {
    setDragDepth(0)
    setCaretX(null)
    useUiStore.getState().setMotionDragActive(false)
    if (!accepts(e)) return
    e.preventDefault()
    const raw = e.dataTransfer.getData(MOTION_MIME)
    if (!raw) return
    const payload = JSON.parse(raw) as DroppedMotionPayload
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const rawStart = Math.max(0, (e.clientX - rect.left) / pps)
    const startTime = snapTime(rawStart, buildSnapContext('__new__')).time
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

  // Click/drag on empty lane → scrub the playhead.
  const onPointerDown = (e: React.PointerEvent): void => {
    e.currentTarget.setPointerCapture(e.pointerId)
    scrubbing.current = true
    seekToX(e.clientX, e.currentTarget, pps, duration)
  }
  const onPointerMove = (e: React.PointerEvent): void => {
    if (!scrubbing.current) return
    seekToX(e.clientX, e.currentTarget, pps, duration)
  }
  const onPointerUp = (e: React.PointerEvent): void => {
    scrubbing.current = false
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }

  const bodyClass = [
    'relative',
    motionDragActive && canDropMotion && !isHover ? 'ring-1 ring-inset ring-blue-500/40' : '',
    isHover && canDropMotion ? 'bg-blue-500/15 ring-2 ring-inset ring-blue-400/70' : '',
    motionDragActive && !canDropMotion ? 'opacity-40' : ''
  ]
    .filter(Boolean)
    .join(' ')

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
        {motionDragActive && !canDropMotion && (
          <span className="ml-auto text-[10px] text-zinc-500">🚫</span>
        )}
      </div>
      <div
        className={bodyClass}
        style={{ width, height: LANE_HEIGHT, touchAction: 'none' }}
        onDragEnter={onDragEnter}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
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
        {isHover && canDropMotion && caretX !== null && (
          <div
            className="tm-caret pointer-events-none absolute top-0 z-30 h-full w-0.5 bg-blue-300"
            style={{ left: caretX }}
          >
            <div className="absolute -left-1 -top-1 h-2 w-2 rounded-full bg-blue-300" />
          </div>
        )}
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
  // `base` is the frozen value of whichever field this drag resizes (startTime
  // for 'move', duration for 'l'/'r'); `baseStart` freezes the start so the
  // 'l' branch can pin the RIGHT edge instead of reading live, already-mutated
  // values (which compounded the cumulative dx every move event).
  const [drag, setDrag] = useState<
    null | { mode: 'move' | 'l' | 'r'; startX: number; base: number; baseStart: number }
  >(null)

  const onPointerDown = (e: React.PointerEvent, mode: 'move' | 'l' | 'r'): void => {
    if (locked) return
    e.stopPropagation()
    onSelect(clip.id)
    e.currentTarget.setPointerCapture(e.pointerId)
    setDrag({
      mode,
      startX: e.clientX,
      base: mode === 'move' ? clip.startTime : clip.duration,
      baseStart: clip.startTime
    })
  }

  const onPointerMove = (e: React.PointerEvent): void => {
    if (!drag) return
    const dx = (e.clientX - drag.startX) / pps
    const store = useTimelineStore.getState()
    const sctx = buildSnapContext(clip.id)
    if (drag.mode === 'move') {
      const candidate = Math.max(0, drag.base + dx)
      // Snap whichever edge is closer to a target: the leading (start) or the
      // trailing (end), so a clip butts against a neighbour on either side.
      const snappedStart = snapTime(candidate, sctx)
      const snappedEnd = snapTime(candidate + clip.duration, sctx)
      let newStart = candidate
      const startHit = snappedStart.matchedTarget !== null
      const endHit = snappedEnd.matchedTarget !== null
      if (startHit && endHit) {
        newStart =
          Math.abs(candidate - snappedStart.time) <=
          Math.abs(candidate + clip.duration - snappedEnd.time)
            ? snappedStart.time
            : Math.max(0, snappedEnd.time - clip.duration)
      } else if (startHit) {
        newStart = snappedStart.time
      } else if (endHit) {
        newStart = Math.max(0, snappedEnd.time - clip.duration)
      }
      store.moveClip(clip.id, Math.max(0, newStart))
    } else if (drag.mode === 'l') {
      // Pin the frozen right edge (baseStart + base); only the start moves, so
      // the clip trims without drifting — mirrors how 'r' pins the start. The
      // upper cap keeps a 0.1s minimum, but never below baseStart (so a sub-0.1s
      // clip can't be made to jump backward by trimming its left edge).
      const frozenEnd = drag.baseStart + drag.base
      const maxStart = Math.max(drag.baseStart, frozenEnd - 0.1)
      const raw = Math.max(0, Math.min(drag.baseStart + dx, maxStart))
      const snapped = snapTime(raw, sctx)
      const newStart = snapped.matchedTarget !== null ? Math.min(snapped.time, maxStart) : raw
      store.trimClip(clip.id, newStart, frozenEnd)
    } else {
      const rawEnd = drag.baseStart + Math.max(0.1, drag.base + dx)
      const snapped = snapTime(rawEnd, sctx)
      const newEnd = snapped.matchedTarget !== null ? Math.max(drag.baseStart + 0.1, snapped.time) : rawEnd
      store.trimClip(clip.id, drag.baseStart, newEnd)
    }
  }

  const onPointerUp = (e: React.PointerEvent): void => {
    if (drag) {
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        /* ignore */
      }
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
            className="absolute left-0 top-0 h-full w-2 cursor-ew-resize rounded-l bg-black/30 hover:bg-white/50"
            onPointerDown={(e) => onPointerDown(e, 'l')}
          />
          <span
            className="absolute right-0 top-0 h-full w-2 cursor-ew-resize rounded-r bg-black/30 hover:bg-white/50"
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
