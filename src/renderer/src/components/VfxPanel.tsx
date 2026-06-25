import { useVfxStore } from '@renderer/stores/vfxStore'
import { Slider, ColorInput, Toggle, SectionTitle, Select } from './ui'

export function VfxPanel(): React.JSX.Element {
  const glow = useVfxStore((s) => s.config.glowstick)
  const post = useVfxStore((s) => s.config.postProcess)
  const store = useVfxStore.getState()

  return (
    <div>
      <SectionTitle>荧光棒 / Glowstick</SectionTitle>
      <Toggle label="启用荧光棒" value={glow.enabled} onChange={(v) => store.setGlowEnabled(v)} />
      <Toggle label="拖尾 Trail" value={glow.trail} onChange={(v) => store.setTrailEnabled(v)} />
      <Toggle label="双持 Double Wield" value={glow.doubleWield} onChange={(v) => store.setDoubleWield(v)} />

      <div className="mt-2 grid grid-cols-2 gap-2">
        <div>
          <div className="mb-1 text-xs text-zinc-400">右手 Right</div>
          <ColorInput label="颜色" value={glow.rightHand.color} onChange={(v) => store.setGlowColor('right', v)} />
          <Slider label="亮度" value={glow.rightHand.intensity} min={0} max={6} onChange={(v) => store.setGlowIntensity('right', v)} />
          <Slider label="光照" value={glow.rightHand.lightIntensity} min={0} max={2} onChange={(v) => store.setLightIntensity('right', v)} />
        </div>
        <div>
          <div className="mb-1 text-xs text-zinc-400">左手 Left</div>
          <ColorInput label="颜色" value={glow.leftHand.color} onChange={(v) => store.setGlowColor('left', v)} />
          <Slider label="亮度" value={glow.leftHand.intensity} min={0} max={6} onChange={(v) => store.setGlowIntensity('left', v)} />
          <Slider label="光照" value={glow.leftHand.lightIntensity} min={0} max={2} onChange={(v) => store.setLightIntensity('left', v)} />
        </div>
      </div>

      <SectionTitle>后期 / Post-Processing</SectionTitle>
      <Toggle label="Bloom 泛光" value={post.bloomEnabled} onChange={(v) => store.setPost({ bloomEnabled: v })} />
      <Slider label="Bloom 阈值" value={post.bloomThreshold} min={0} max={1} onChange={(v) => store.setPost({ bloomThreshold: v })} />
      <Slider label="Bloom 强度" value={post.bloomWeight} min={0} max={2} onChange={(v) => store.setPost({ bloomWeight: v })} />
      <Slider label="Bloom 模糊核" value={post.bloomKernel} min={1} max={128} step={1} onChange={(v) => store.setPost({ bloomKernel: v })} />
      <Slider label="曝光 Exposure" value={post.exposure} min={0} max={3} onChange={(v) => store.setPost({ exposure: v })} />
      <Slider label="对比度 Contrast" value={post.contrast} min={0} max={3} onChange={(v) => store.setPost({ contrast: v })} />
      <Toggle label="暗角 Vignette" value={post.vignetteEnabled} onChange={(v) => store.setPost({ vignetteEnabled: v })} />
      <Slider label="暗角强度" value={post.vignetteWeight} min={0} max={10} onChange={(v) => store.setPost({ vignetteWeight: v })} />
      <Toggle label="锐化 Sharpen" value={post.sharpenEnabled} onChange={(v) => store.setPost({ sharpenEnabled: v })} />

      <Select
        label="预设 Preset"
        value={'custom' as string}
        options={[
          { value: 'custom', label: '自定义 Custom' },
          { value: 'reset', label: '↺ 重置默认' }
        ]}
        onChange={(v) => {
          if (v === 'reset') {
            import('@shared/types/vfx').then(({ DEFAULT_VFX_CONFIG }) =>
              store.loadFromProject(structuredClone(DEFAULT_VFX_CONFIG))
            )
          }
        }}
      />
    </div>
  )
}
