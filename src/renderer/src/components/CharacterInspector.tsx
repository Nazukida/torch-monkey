import { useCharacterStore } from '@renderer/stores/characterStore'
import { Slider, ColorInput, Toggle, SectionTitle, Button } from './ui'

export function CharacterInspector(): React.JSX.Element {
  const selectedId = useCharacterStore((s) => s.selectedId)
  const cfg = useCharacterStore((s) => (s.selectedId ? s.configs[s.selectedId] : null))
  const store = useCharacterStore.getState()

  if (!selectedId || !cfg) {
    return <div className="px-2 py-4 text-center text-xs text-zinc-500">未选中角色</div>
  }

  const upd = (partial: Parameters<typeof store.updateConfig>[1]) => store.updateConfig(selectedId, partial)

  return (
    <div>
      <SectionTitle>角色 / Character</SectionTitle>
      <div className="mb-2">
        <div className="mb-1 text-xs text-zinc-400">名称 Name</div>
        <input
          className="w-full rounded bg-zinc-800 px-2 py-1 text-sm outline-none"
          value={cfg.name}
          onChange={(e) => upd({ name: e.target.value })}
        />
      </div>

      <Slider
        label="身高 Height"
        value={cfg.height}
        min={1.0}
        max={2.5}
        step={0.01}
        onChange={(v) => upd({ height: v })}
        format={(v) => `${v.toFixed(2)} m`}
      />
      <ColorInput label="颜色 Color" value={cfg.color} onChange={(v) => upd({ color: v })} />
      <Slider
        label="不透明度 Opacity"
        value={cfg.opacity}
        min={0.1}
        max={1}
        onChange={(v) => upd({ opacity: v })}
      />

      <SectionTitle>站位 / Placement</SectionTitle>
      <Slider
        label="X"
        value={cfg.position[0]}
        min={-10}
        max={10}
        step={0.1}
        onChange={(v) => upd({ position: [v, cfg.position[1], cfg.position[2]] })}
        format={(v) => v.toFixed(1)}
      />
      <Slider
        label="Z"
        value={cfg.position[2]}
        min={-10}
        max={10}
        step={0.1}
        onChange={(v) => upd({ position: [cfg.position[0], cfg.position[1], v] })}
        format={(v) => v.toFixed(1)}
      />
      <Slider
        label="朝向 Rotation"
        value={cfg.rotation}
        min={-180}
        max={180}
        step={1}
        onChange={(v) => upd({ rotation: v })}
        format={(v) => `${v.toFixed(0)}°`}
      />

      <SectionTitle>显示 / Display</SectionTitle>
      <Toggle label="显示骨骼 Show Skeleton" value={cfg.showSkeleton} onChange={(v) => upd({ showSkeleton: v })} />
      <div className="mt-3">
        <Button onClick={() => store.duplicateCharacter(selectedId)}>复制角色</Button>
      </div>
    </div>
  )
}
