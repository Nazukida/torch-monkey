import { useEffect, useState } from 'react'
import { ViewportContainer } from './components/ViewportContainer'
import { LeftPanel } from './components/LeftPanel'
import { RightPanel } from './components/RightPanel'
import { TimelineContainer } from './timeline/TimelineContainer'
import { TopBar } from './components/TopBar'
import { useMotionStore } from './stores/motionStore'
import { useProjectStore } from './stores/projectStore'
import { useCharacterStore } from './stores/characterStore'
import { useTimelineStore } from './stores/timelineStore'
import { bindKeyboardShortcuts } from './lib/keyboard'
import { importVideoForCapture } from './lib/capture'

export default function App(): React.JSX.Element {
  const [pythonStatus, setPythonStatus] = useState<'checking' | 'ok' | 'down'>('checking')

  useEffect(() => {
    useMotionStore.getState().loadMotionList()
    window.electronAPI
      .pythonHealth()
      .then((h) => setPythonStatus(h.status === 'ok' ? 'ok' : 'down'))

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
      }
    })
    const offKeys = bindKeyboardShortcuts()

    return () => {
      offProgress()
      offMenu()
      offKeys()
    }
  }, [])

  return (
    <div className="flex h-screen w-screen flex-col bg-zinc-950 text-zinc-200 select-none">
      <TopBar pythonStatus={pythonStatus} />
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
    </div>
  )
}

