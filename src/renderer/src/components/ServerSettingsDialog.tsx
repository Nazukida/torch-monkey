import { useEffect, useState } from 'react'
import { useUiStore } from '@renderer/stores/uiStore'
import type {
  ConnectionTestResult,
  PythonConfig,
  PythonRuntime
} from '@shared/types/electron'

/** UI-only mode selector; both remote variants map to PythonMode 'remote'. */
type UiMode = 'local' | 'remote-ssh' | 'remote-lan'

/**
 * Modal for choosing where the AI mocap pipeline runs and how the client
 * reaches it.
 *
 * 三种模式 / three modes:
 *  - 本地 (local):      spawn server.py on this machine (historical default).
 *  - 远程-SSH 隧道:     server on a Linux GPU box, reached via
 *                        `ssh -L 19876:127.0.0.1:19876 user@server`; URL stays
 *                        http://127.0.0.1:19876.
 *  - 远程-局域网:       server started with `--host 0.0.0.0`; URL is
 *                        http://<server-ip>:19876.
 *
 * 「测试连接」会探测目标 /api/health ��回显 device / CUDA / GPU，让你确认转发
 * 是否真的落到了 GPU 机器上（这正是修复「点开后没转发到我电脑」的关键）。
 */
export function ServerSettingsDialog({
  onConfigured
}: {
  onConfigured?: () => void
}): React.JSX.Element | null {
  const open = useUiStore((s) => s.serverSettingsOpen)
  const close = useUiStore((s) => s.closeServerSettings)

  const [uiMode, setUiMode] = useState<UiMode>('local')
  const [remoteUrl, setRemoteUrl] = useState('http://127.0.0.1:19876')
  const [port, setPort] = useState(19876)
  const [loaded, setLoaded] = useState(false)

  const [testing, setTesting] = useState(false)
  const [test, setTest] = useState<ConnectionTestResult | null>(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  // Prefill from the persisted config whenever the dialog opens.
  useEffect(() => {
    if (!open) return
    setTest(null)
    setMsg(null)
    window.electronAPI
      .pythonGetConfig()
      .then((cfg: PythonConfig) => {
        setUiMode(cfg.mode === 'remote' ? 'remote-ssh' : 'local')
        if (cfg.remoteUrl) setRemoteUrl(cfg.remoteUrl)
        if (cfg.port) setPort(cfg.port)
      })
      .catch(() => undefined)
      .finally(() => setLoaded(true))
  }, [open])

  if (!open) return null

  const isRemote = uiMode !== 'local'

  const targetUrl = (): string => (isRemote ? remoteUrl : `http://127.0.0.1:${port}`)

  const onTest = async (): Promise<void> => {
    setTesting(true)
    setTest(null)
    setMsg(null)
    try {
      const res = await window.electronAPI.pythonTestConnection(targetUrl())
      setTest(res)
    } catch (e) {
      setTest({ ok: false, error: (e as Error).message })
    } finally {
      setTesting(false)
    }
  }

  const onSave = async (): Promise<void> => {
    setSaving(true)
    setMsg(null)
    try {
      const health = await window.electronAPI.pythonConfigure({
        mode: isRemote ? 'remote' : 'local',
        remoteUrl: isRemote ? remoteUrl.trim() : '',
        port: Math.max(1, Math.round(port) || 19876)
      })
      if (health.status === 'ok') {
        setMsg({ kind: 'ok', text: '✅ 已保存并连接 / saved & connected' })
        onConfigured?.()
      } else {
        setMsg({
          kind: 'err',
          text: '已保存，但当前连不上 / saved, but unreachable now — 点「测试连接」排查。'
        })
        onConfigured?.()
      }
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={() => !saving && close()}
    >
      <div
        className="w-[34rem] rounded-lg border border-zinc-700 bg-zinc-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-zinc-100">
            ⚙ AI 管线 / 服务器设置 — Pipeline Connection
          </h2>
          <button
            className="text-zinc-500 hover:text-zinc-200"
            onClick={() => !saving && close()}
            disabled={saving}
          >
            ✕
          </button>
        </div>

        {/* Mode */}
        <div className="mb-1 text-xs text-zinc-400">模式 / Mode</div>
        <div className="mb-3 grid grid-cols-3 gap-2 text-xs">
          {(
            [
              { v: 'local', label: '🖥 本地 Local' },
              { v: 'remote-ssh', label: '🔗 远程·SSH 隧道' },
              { v: 'remote-lan', label: '🌐 远程·局域网 LAN' }
            ] as { v: UiMode; label: string }[]
          ).map((o) => (
            <button
              key={o.v}
              className={`rounded border px-2 py-2 ${
                uiMode === o.v
                  ? 'border-blue-500 bg-blue-600/20 text-zinc-100'
                  : 'border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
              }`}
              onClick={() => {
                setUiMode(o.v)
                setTest(null)
                setMsg(null)
              }}
            >
              {o.label}
            </button>
          ))}
        </div>

        {/* URL or port */}
        {isRemote ? (
          <>
            <label className="mb-1 block text-xs text-zinc-400">
              服务器地址 / Server URL
            </label>
            <input
              className="mb-2 w-full rounded bg-zinc-800 px-2 py-1.5 text-sm outline-none focus:bg-zinc-700"
              placeholder={
                uiMode === 'remote-ssh'
                  ? 'http://127.0.0.1:19876'
                  : 'http://192.168.1.50:19876'
              }
              value={remoteUrl}
              onChange={(e) => {
                setRemoteUrl(e.target.value)
                setTest(null)
                setMsg(null)
              }}
              disabled={saving}
            />
            <div className="mb-2 rounded bg-zinc-800/60 p-2 text-[11px] leading-relaxed text-zinc-400">
              {uiMode === 'remote-ssh' ? (
                <>
                  在 Linux 服务器上运行 <code className="text-zinc-300">python server.py</code>，然后在本机执行：
                  <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all text-emerald-300">
                    ssh -L 19876:127.0.0.1:19876 user@your-server
                  </pre>
                  隧道打通后地址保持 <code className="text-zinc-300">http://127.0.0.1:19876</code>。
                </>
              ) : (
                <>
                  在服务器上以 <code className="text-zinc-300">python server.py --host 0.0.0.0</code>
                  （或 <code className="text-zinc-300">TORCHMONKEY_HOST=0.0.0.0</code>）启动，地址填服务器 IP。
                  ⚠️ 需自行放行防火墙端口，仅限可信内网。
                </>
              )}
            </div>
          </>
        ) : (
          <>
            <label className="mb-1 block text-xs text-zinc-400">本地端口 / Local port</label>
            <input
              type="number"
              min={1}
              max={65535}
              className="mb-2 w-40 rounded bg-zinc-800 px-2 py-1.5 text-sm outline-none focus:bg-zinc-700"
              value={port}
              onChange={(e) => {
                setPort(parseInt(e.target.value) || 19876)
                setTest(null)
                setMsg(null)
              }}
              disabled={saving}
            />
            <div className="mb-2 text-[11px] text-zinc-500">
              本机 spawn <code>python/server.py</code>；需要本机已安装 Python 与依赖。
            </div>
          </>
        )}

        {/* Test connection */}
        <div className="flex items-center gap-2">
          <button
            className="rounded bg-zinc-800 px-3 py-1.5 text-xs hover:bg-zinc-700 disabled:opacity-50"
            onClick={() => void onTest()}
            disabled={testing || saving || !loaded}
          >
            {testing ? '测试中…' : '🔍 测试连接 Test'}
          </button>
          {test && <TestBadge result={test} />}
        </div>

        {/* Save */}
        <button
          className="mt-4 w-full rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          onClick={() => void onSave()}
          disabled={saving || !loaded}
        >
          {saving ? '应用中…' : '💾 保存并应用 Save & Apply'}
        </button>
        {msg && (
          <div
            className={`mt-2 text-center text-xs ${
              msg.kind === 'ok' ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {msg.text}
          </div>
        )}

        <p className="mt-3 text-[10px] leading-relaxed text-zinc-500">
          提示：远程模式下大视频需上传到服务器，较慢；远程优先用「📺 B 站动捕」（只传 BV 号）。
        </p>
      </div>
    </div>
  )
}

function TestBadge({ result }: { result: ConnectionTestResult }): React.JSX.Element {
  if (result.ok) {
    return (
      <span className="text-xs text-emerald-400">
        ✅ {runtimeSummary(result.runtime)}
        {typeof result.latencyMs === 'number' ? ` · ${Math.round(result.latencyMs)}ms` : ''}
      </span>
    )
  }
  return <span className="text-xs text-red-400">❌ {result.error ?? '连接失败 / failed'}</span>
}

/** Render a compact device/CUDA summary from a /api/health runtime block. */
function runtimeSummary(rt?: PythonRuntime): string {
  if (!rt) return 'ok'
  if (rt.cuda_available) {
    const name = rt.device_name ?? 'cuda'
    let vram = ''
    if (rt.gpu_mem_total_mb) {
      vram = ` · ${((rt.gpu_mem_used_mb ?? 0) / 1024).toFixed(1)}/${(rt.gpu_mem_total_mb / 1024).toFixed(0)}GB`
    }
    return `cuda · ${name}${vram}`
  }
  if (rt.torch_installed) return `cpu · torch ${rt.torch_version ?? '?'}`
  return 'torch 未安装 / torch missing'
}
