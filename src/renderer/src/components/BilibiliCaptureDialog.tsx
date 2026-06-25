import { useEffect, useState } from 'react'
import { useUiStore } from '@renderer/stores/uiStore'
import { probeBilibili, captureFromBilibili } from '@renderer/lib/bilibili'
import type { BilibiliVideoInfo } from '@shared/types/electron'

/**
 * Modal for capturing a motion from a Bilibili video (BV 号 / BV id).
 *
 * 流程：输入 BV 号 →（可选）探测元信息 → 一键下载并送入 AI 动捕管线 →
 * 结果进入动作库。详见 USAGE.md「B 站动捕（BV 号）」。
 */
export function BilibiliCaptureDialog(): React.JSX.Element | null {
  const open = useUiStore((s) => s.bilibiliOpen)
  const close = useUiStore((s) => s.closeBilibili)

  const [bvid, setBvid] = useState('')
  const [page, setPage] = useState(1)
  const [fps, setFps] = useState(30)
  const [smooth, setSmooth] = useState(true)
  const [detectKime, setDetectKime] = useState(true)

  const [info, setInfo] = useState<BilibiliVideoInfo | null>(null)
  const [probing, setProbing] = useState(false)
  const [probeError, setProbeError] = useState<string | null>(null)

  const [capturing, setCapturing] = useState(false)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [doneMsg, setDoneMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Subscribe to pipeline progress while capturing.
  useEffect(() => {
    if (!open) return
    const off = window.electronAPI.onProgress((e) => {
      if (e.phase === 'done' || e.phase === 'error') return
      setStatusMsg(`${phaseLabel(e.phase)} ${Math.round(e.progress * 100)}%`)
    })
    return () => off()
  }, [open])

  // Reset transient state whenever the dialog (re)opens.
  useEffect(() => {
    if (open) {
      setInfo(null)
      setProbeError(null)
      setStatusMsg(null)
      setDoneMsg(null)
      setError(null)
    }
  }, [open])

  if (!open) return null

  const onProbe = async (): Promise<void> => {
    if (!bvid.trim()) return
    setProbing(true)
    setProbeError(null)
    setInfo(null)
    try {
      const res = await probeBilibili(bvid.trim(), page > 1 ? page : undefined)
      if (res.error || !res.info) setProbeError(res.error ?? '探测失败')
      else setInfo(res.info)
    } catch (e) {
      setProbeError((e as Error).message)
    } finally {
      setProbing(false)
    }
  }

  const onCapture = async (): Promise<void> => {
    if (!bvid.trim()) return
    setCapturing(true)
    setError(null)
    setDoneMsg(null)
    setStatusMsg('下载中… Downloading…')
    try {
      const { motion, source } = await captureFromBilibili(bvid.trim(), {
        page: page > 1 ? page : undefined,
        fps,
        smooth,
        detectKime
      })
      const kime = motion.beatMarkers.filter((b) => b.type === 'kime').length
      setDoneMsg(
        `✅ 已入库：${motion.name} · ${motion.frameCount} 帧 · 卡点 ${kime}` +
          (source ? ` · ${Math.round(source.duration)}s` : '')
      )
      setStatusMsg(null)
    } catch (e) {
      setError((e as Error).message)
      setStatusMsg(null)
    } finally {
      setCapturing(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={() => !capturing && close()}
    >
      <div
        className="w-[30rem] rounded-lg border border-zinc-700 bg-zinc-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-zinc-100">
            📺 B 站动捕 / Bilibili Capture（BV 号）
          </h2>
          <button
            className="text-zinc-500 hover:text-zinc-200"
            onClick={() => !capturing && close()}
            disabled={capturing}
          >
            ✕
          </button>
        </div>

        <label className="mb-1 block text-xs text-zinc-400">BV 号 / BV id 或 bilibili 链接</label>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded bg-zinc-800 px-2 py-1.5 text-sm outline-none focus:bg-zinc-700"
            placeholder="BV1xx411c7mD 或 https://www.bilibili.com/video/..."
            value={bvid}
            onChange={(e) => setBvid(e.target.value)}
            disabled={capturing}
            autoFocus
          />
          <button
            className="rounded bg-zinc-800 px-3 py-1.5 text-xs hover:bg-zinc-700 disabled:opacity-50"
            onClick={() => void onProbe()}
            disabled={probing || capturing || !bvid.trim()}
          >
            {probing ? '探测中…' : '🔍 探测'}
          </button>
        </div>

        {probeError && <div className="mt-2 text-xs text-red-400">{probeError}</div>}
        {info && (
          <div className="mt-2 rounded bg-zinc-800/60 p-2 text-xs text-zinc-300">
            <div className="truncate font-medium">{info.title}</div>
            <div className="mt-0.5 text-zinc-500">
              {info.uploader && <span>{info.uploader} · </span>}
              <span>{Math.round(info.duration)}s</span>
              {info.bvid && <span> · {info.bvid}</span>}
            </div>
          </div>
        )}

        <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div>
            <div className="mb-1 text-zinc-400">分P Page</div>
            <input
              type="number"
              min={1}
              className="w-full rounded bg-zinc-800 px-2 py-1 outline-none"
              value={page}
              onChange={(e) => setPage(Math.max(1, parseInt(e.target.value) || 1))}
              disabled={capturing}
            />
          </div>
          <div>
            <div className="mb-1 text-zinc-400">FPS</div>
            <select
              className="w-full rounded bg-zinc-800 px-1 py-1 outline-none"
              value={fps}
              onChange={(e) => setFps(parseInt(e.target.value))}
              disabled={capturing}
            >
              <option value={30}>30</option>
              <option value={60}>60</option>
            </select>
          </div>
          <div className="flex items-end gap-3">
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={smooth}
                onChange={(e) => setSmooth(e.target.checked)}
                disabled={capturing}
              />
              平滑
            </label>
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={detectKime}
                onChange={(e) => setDetectKime(e.target.checked)}
                disabled={capturing}
              />
              卡点
            </label>
          </div>
        </div>

        <button
          className="mt-4 w-full rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          onClick={() => void onCapture()}
          disabled={capturing || !bvid.trim()}
        >
          {capturing ? (statusMsg ?? '处理中…') : '⬇️ 下载并动捕（Download & Capture）'}
        </button>

        {statusMsg && capturing && (
          <div className="mt-2 text-center text-xs text-zinc-400">{statusMsg}</div>
        )}
        {doneMsg && <div className="mt-2 text-center text-xs text-emerald-400">{doneMsg}</div>}
        {error && <div className="mt-2 text-center text-xs text-red-400">{error}</div>}

        <p className="mt-3 text-[10px] leading-relaxed text-zinc-500">
          ⚖️ 仅下载你<strong>有权使用</strong>的视频（如你自己的表演、或已获授权的内容），用于本地动作分析，不得再分发（redistributed）。
          需要 yt-dlp（<code className="text-zinc-400">pip install yt-dlp</code>）。
        </p>
      </div>
    </div>
  )
}

function phaseLabel(phase: string): string {
  switch (phase) {
    case 'download':
      return '下载 Download'
    case 'frames':
      return '抽帧 Frames'
    case 'pose2d':
      return '2D 关键点'
    case 'pose3d':
      return '3D 提升'
    case 'optimize':
      return '打艺优化'
    case 'export':
      return '导出 Export'
    default:
      return phase
  }
}
