import { useState } from 'react'
import { MotionLibrary } from '@renderer/motion/MotionLibrary'
import { CharacterListPanel } from './CharacterListPanel'

type Tab = 'motions' | 'characters'

export function LeftPanel(): React.JSX.Element {
  const [tab, setTab] = useState<Tab>('motions')
  return (
    <div className="flex w-72 flex-col border-r border-zinc-800 bg-zinc-900/60">
      <div className="flex border-b border-zinc-800 text-xs">
        {(['motions', 'characters'] as Tab[]).map((t) => (
          <button
            key={t}
            className={`flex-1 py-2 ${tab === t ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'}`}
            onClick={() => setTab(t)}
          >
            {t === 'motions' ? '🎬 动作库' : '👥 角色'}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === 'motions' ? <MotionLibrary /> : <CharacterListPanel />}
      </div>
    </div>
  )
}
