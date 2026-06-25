import { useCharacterStore } from '@renderer/stores/characterStore'
import { Button } from './ui'

export function CharacterListPanel(): React.JSX.Element {
  const configs = useCharacterStore((s) => s.configs)
  const selectedId = useCharacterStore((s) => s.selectedId)
  const list = Object.values(configs)

  return (
    <div className="flex flex-col gap-1 p-2">
      <div className="mb-1 flex gap-1">
        <Button variant="primary" onClick={() => useCharacterStore.getState().addCharacter()}>
          ＋ 新增角色
        </Button>
        <Button
          onClick={() => useCharacterStore.getState().alignCharacters('row')}
          disabled={list.length < 2}
        >
          一字排开
        </Button>
        <Button
          onClick={() => useCharacterStore.getState().alignCharacters('v-formation')}
          disabled={list.length < 2}
        >
          V 字
        </Button>
      </div>
      {list.map((c) => (
        <div
          key={c.id}
          className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm ${
            selectedId === c.id ? 'bg-blue-600/30 ring-1 ring-blue-500' : 'hover:bg-zinc-800'
          }`}
          onClick={() => useCharacterStore.getState().selectCharacter(c.id)}
        >
          <span
            className="inline-block h-3 w-3 rounded-full"
            style={{ backgroundColor: c.visible ? c.color : '#555' }}
          />
          <span className="flex-1 truncate">{c.name}</span>
          <button
            className="text-zinc-500 hover:text-zinc-200"
            title={c.visible ? '隐藏' : '显示'}
            onClick={(e) => {
              e.stopPropagation()
              useCharacterStore.getState().updateConfig(c.id, { visible: !c.visible })
            }}
          >
            {c.visible ? '👁' : '🚫'}
          </button>
          <button
            className="text-zinc-500 hover:text-red-400"
            title="删除"
            onClick={(e) => {
              e.stopPropagation()
              useCharacterStore.getState().removeCharacter(c.id)
            }}
          >
            🗑
          </button>
        </div>
      ))}
      {list.length === 0 && <div className="px-2 py-4 text-center text-xs text-zinc-500">暂无角色</div>}
    </div>
  )
}
