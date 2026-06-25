import { useState } from 'react'
import { StageConfigPanel } from './StageConfigPanel'
import { CharacterInspector } from './CharacterInspector'
import { VfxPanel } from './VfxPanel'

type Tab = 'stage' | 'character' | 'vfx'

export function RightPanel(): React.JSX.Element {
  const [tab, setTab] = useState<Tab>('stage')
  return (
    <div className="flex w-80 flex-col border-l border-zinc-800 bg-zinc-900/60">
      <div className="flex border-b border-zinc-800 text-xs">
        {(
          [
            ['stage', '🎬 舞台'],
            ['character', '🧍 角色'],
            ['vfx', '✨ 特效']
          ] as [Tab, string][]
        ).map(([t, label]) => (
          <button
            key={t}
            className={`flex-1 py-2 ${tab === t ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'}`}
            onClick={() => setTab(t)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === 'stage' && <StageConfigPanel />}
        {tab === 'character' && <CharacterInspector />}
        {tab === 'vfx' && <VfxPanel />}
      </div>
    </div>
  )
}
