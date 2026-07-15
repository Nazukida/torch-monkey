import { useCallback, useEffect, useState } from 'react'
import { ViewportContainer } from './components/ViewportContainer'
import { LeftPanel } from './components/LeftPanel'
import { RightPanel } from './components/RightPanel'
import { TimelineContainer } from './timeline/TimelineContainer'
import { TopBar } from './components/TopBar'
import { BilibiliCaptureDialog } from './components/BilibiliCaptureDialog'
import { ServerSettingsDialog } from './components/ServerSettingsDialog'
import { useMotionStore } from './stores/motionStore'
import { useProjectStore } from './stores/projectStore'
import { useCharacterStore } from './stores/characterStore'
import { useTimelineStore } from './stores/timelineStore'
import { bindKeyboardShortcuts } from './lib/keyboard'
import { importVideoForCapture } from './lib/capture'
import type { PythonHealthResult } from '@shared/types/electron'

/** Compact connection summary for the top bar, e.g. "远程·cuda:0" / "本地·cpu". */
function summarize(h: PythonHealthResult | null): string {
  if (!h || h.status !== 'ok') return ''
  const where = h.endpoint?.mode === 'remote' ? '远程' : '本地'
  const rt = h.runtime
  let dev = ''
  if (rt?.cuda_available) dev = 'cuda'
  else if (rt?.torch_installed) dev = 'cpu'
  return dev ? `${where}·${dev}` : where
}

export default function App(): React.JSX.Element {
  const [health, setHealth] = useState<PythonHealthResult | null>(null)
  const [checking, setChecking] = useState(true)

  const refreshPythonStatus = useCallback(async () => {
    try {
      setHealth(await window.electronAPI.pythonHealth())
    } catch {
      setHealth(null)
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    useMotionStore.getState().loadMotionList()
    void refreshPythonStatus()
    // Re-probe periodically so the indicator + remote device summary stay live.
    const poll = window.setInterval(() => {
      void refreshPythonStatus()
    }, 8000)

    // Seed a starter project if empty: one character + one character track.
    const chars = useCharacterStore.getState()
    if (Object.keys(chars.configs).length === 0) {
      const id = chars.addCharacter({ name: 'Player 1', position: [0, 0, 1] })
      useTimelineStore.getState().addTrack('character', id, 'Player 1')
    }

    const offProgress = window.electronAPI.onProgress((e) => {
      console.debug('[progress]', e.phase, e.progress, e.message ?? '')
    })
    const offMenu = window.electronAPI.onMenu((action) => {
      switch (action) {
        case 'newProject':
          useProjectStore.getState().newProject()
          break
        case 'openProject':
          void useProjectStore.getState().open()
          break
        case 'saveProject':
          void useProjectStore.getState().save()
          break
        case 'saveProjectAs':
          void useProjectStore.getState().saveAs()
          break
        case 'importVideo':
          void importVideoForCapture()
          break
        case 'about':
          window.alert('Torch Monkey\nWota-艺 3D 编排与可视化软件\n\n版本 1.0.0\nMIT License')
          break
      }
    })
    const offKeys = bindKeyboardShortcuts()

    return () => {
      window.clearInterval(poll)
      offProgress()
      offMenu()
      offKeys()
    }
  }, [refreshPythonStatus])

  const pythonStatus: 'checking' | 'ok' | 'down' = checking
    ? 'checking'
    : health?.status === 'ok'
      ? 'ok'
      : 'down'

  return (
    <div className="flex h-screen w-screen flex-col bg-zinc-950 text-zinc-200 select-none">
      <TopBar pythonStatus={pythonStatus} pythonSummary={summarize(health)} />
      <div className="flex flex-1 min-h-0">
        <LeftPanel />
        <div className="flex flex-1 min-w-0 flex-col">
          <div className="flex-1 min-h-0">
            <ViewportContainer />
          </div>
          <TimelineContainer />
        </div>
        <RightPanel />
      </div>
      <BilibiliCaptureDialog />
      <ServerSettingsDialog onConfigured={() => void refreshPythonStatus()} />
    </div>
  )
}
