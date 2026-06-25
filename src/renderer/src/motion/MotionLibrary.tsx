import { useEffect } from 'react'
import { useMotionStore } from '@renderer/stores/motionStore'
import { useUiStore } from '@renderer/stores/uiStore'
import { importVideoForCapture } from '@renderer/lib/capture'
import { createSampleMotions } from '@renderer/lib/sampleMotions'
import type { MotionMeta } from '@shared/types/motion'

export function MotionLibrary(): React.JSX.Element {
  const list = useMotionStore((s) => s.motionList)
  const selectedId = useMotionStore((s) => s.selectedId)
  const search = useMotionStore((s) => s.searchQuery)
  const store = useMotionStore.getState()

  useEffect(() => {
    void store.loadMotionList()
  }, [search, store])

  const onDragStart = (e: React.DragEvent, m: MotionMeta): void => {
    const payload = {
      motionId: m.id,
      motionName: m.name,
      duration: m.duration,
      frameCount: m.frameCount,
      fps: m.fps
    }
    e.dataTransfer.setData('application/x-torchmonkey-motion', JSON.stringify(payload))
    e.dataTransfer.effectAllowed = 'copy'
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 p-2">
        <input
          className="w-full rounded bg-zinc-800 px-2 py-1 text-sm outline-none"
          placeholder="🔍 搜索动作…"
          value={search}
          onChange={(e) => store.setSearchQuery(e.target.value)}
        />
        <div className="mt-2 flex gap-1">
          <button
            className="flex-1 rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-500"
            onClick={() => importVideoForCapture().catch((e) => alert(`动捕失败: ${e.message}`))}
          >
            🎥 视频动捕
          </button>
          <button
            className="flex-1 rounded bg-fuchsia-700 px-2 py-1 text-xs text-white hover:bg-fuchsia-600"
            onClick={() => useUiStore.getState().openBilibili()}
            title="从 Bilibili BV 号下载并动捕"
          >
            📺 B 站
          </button>
        </div>
        <div className="mt-1 flex gap-1">
          <button
            className="flex-1 rounded bg-zinc-800 px-2 py-1 text-xs hover:bg-zinc-700"
            onClick={() => void createSampleMotions()}
            title="生成内置测试动作 (T-Pose / 画圆 / 鞠躬)"
          >
            ➕ 测试动作
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {list.map((m) => (
          <div
            key={m.id}
            draggable
            onDragStart={(e) => onDragStart(e, m)}
            onClick={() => void store.selectMotion(m.id)}
            className={`mb-1 cursor-pointer rounded border px-2 py-1.5 text-sm ${
              selectedId === m.id
                ? 'border-blue-500 bg-blue-600/20'
                : 'border-transparent hover:bg-zinc-800'
            }`}
          >
            <div className="flex items-center gap-1">
              <span className="flex-1 truncate font-medium text-zinc-200">{m.name}</span>
              <span className="text-[10px] text-zinc-500">{m.source === 'ai-capture' ? 'AI' : '手动'}</span>
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[10px] text-zinc-500">
              <span>{m.duration.toFixed(1)}s</span>
              <span>{m.frameCount}f</span>
              <span className="flex-1">
                <span className="inline-block h-1 rounded bg-zinc-700 align-middle">
                  <span
                    className="block h-1 rounded bg-emerald-500"
                    style={{ width: `${Math.round(m.motionIntensity * 100)}%` }}
                  />
                </span>
              </span>
            </div>
            {m.tags.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {m.tags.slice(0, 3).map((t) => (
                  <span key={t} className="rounded bg-zinc-800 px-1 text-[10px] text-zinc-400">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {list.length === 0 && (
          <div className="px-2 py-6 text-center text-xs text-zinc-500">
            动作库为空。导入视频或生成测试动作。
          </div>
        )}
      </div>

      <div className="border-t border-zinc-800 px-2 py-1 text-[10px] text-zinc-500">
        拖拽动作到下方时间线角色轨道
      </div>
    </div>
  )
}
