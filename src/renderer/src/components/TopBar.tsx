import { useProjectStore } from '@renderer/stores/projectStore'
import { useUiStore } from '@renderer/stores/uiStore'
import { importVideoForCapture } from '@renderer/lib/capture'
import { useState } from 'react'

interface TopBarProps {
  pythonStatus: 'checking' | 'ok' | 'down'
  /** Compact connection summary, e.g. "远程·cuda:0" / "本地·cpu". */
  pythonSummary?: string
}

export function TopBar({ pythonStatus, pythonSummary }: TopBarProps): React.JSX.Element {
  const metadata = useProjectStore((s) => s.metadata)
  const dirty = useProjectStore((s) => s.dirty)
  const save = useProjectStore((s) => s.save)
  const saveAs = useProjectStore((s) => s.saveAs)
  const open = useProjectStore((s) => s.open)
  const newProject = useProjectStore((s) => s.newProject)
  const openServerSettings = useUiStore((s) => s.openServerSettings)
  const [busy, setBusy] = useState(false)

  const statusColor =
    pythonStatus === 'ok' ? 'bg-emerald-500' : pythonStatus === 'down' ? 'bg-red-500' : 'bg-amber-500'
  const statusLabel =
    pythonStatus === 'ok' ? 'AI 管线就绪' : pythonStatus === 'down' ? 'AI 管线离线' : '检测中…'

  return (
    <div className="flex h-11 items-center gap-2 border-b border-zinc-800 bg-zinc-900 px-3">
      <div className="flex items-center gap-2 font-semibold text-zinc-100">
        <span className="text-lg">🔥</span>
        <span>Torch Monkey</span>
      </div>
      <div className="mx-2 h-5 w-px bg-zinc-700" />
      <input
        className="w-56 rounded bg-zinc-800 px-2 py-1 text-sm outline-none focus:bg-zinc-700"
        value={metadata.name}
        onChange={(e) => useProjectStore.getState().setName(e.target.value)}
        placeholder="项目名称"
        id="project-name"
      />
      {dirty && <span className="text-xs text-amber-400">未保存</span>}

      <div className="ml-auto flex items-center gap-1.5 text-xs">
        <button
          className="rounded bg-zinc-800 px-2 py-1 hover:bg-zinc-700"
          onClick={() => newProject()}
        >
          新建
        </button>
        <button
          className="rounded bg-zinc-800 px-2 py-1 hover:bg-zinc-700"
          onClick={() => void open()}
        >
          打开
        </button>
        <button
          className="rounded bg-zinc-800 px-2 py-1 hover:bg-zinc-700"
          onClick={() => void save()}
        >
          保存
        </button>
        <button
          className="rounded bg-zinc-800 px-2 py-1 hover:bg-zinc-700"
          onClick={() => void saveAs()}
        >
          另存为
        </button>
        <div className="mx-1 h-5 w-px bg-zinc-700" />
        <button
          className="rounded bg-blue-600 px-2 py-1 font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          disabled={busy || pythonStatus !== 'ok'}
          onClick={async () => {
            setBusy(true)
            try {
              await importVideoForCapture()
            } catch (e) {
              alert(`动捕失败: ${(e as Error).message}`)
            } finally {
              setBusy(false)
            }
          }}
        >
          🎥 导入视频动捕
        </button>
        <button
          className="rounded bg-fuchsia-700 px-2 py-1 font-medium text-white hover:bg-fuchsia-600 disabled:opacity-50"
          title="从 Bilibili BV 号下载视频并动捕"
          disabled={pythonStatus !== 'ok'}
          onClick={() => useUiStore.getState().openBilibili()}
        >
          📺 B 站动捕
        </button>
        <div className="ml-2 flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${statusColor}`} />
          <span className="text-zinc-400">{statusLabel}</span>
          {pythonSummary && <span className="text-zinc-500">· {pythonSummary}</span>}
          <button
            className="ml-1 rounded px-1.5 py-0.5 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            title="AI 管线 / 服务器设置（本地 / 远程 SSH 隧道 / 局域网）"
            onClick={openServerSettings}
          >
            ⚙
          </button>
        </div>
      </div>
    </div>
  )
}
