import { useStageStore } from '@renderer/stores/stageStore'
import { Slider, ColorInput, Select, Toggle, SectionTitle } from './ui'

export function StageConfigPanel(): React.JSX.Element {
  const config = useStageStore((s) => s.config)
  const light = useStageStore((s) => s.lightConfig)
  const s = useStageStore.getState()

  return (
    <div>
      <SectionTitle>舞台 / Stage</SectionTitle>
      <Slider
        label="宽度 Width"
        value={config.width}
        min={5}
        max={50}
        step={0.5}
        onChange={(v) => s.setWidth(v)}
        format={(v) => `${v.toFixed(1)} m`}
      />
      <Slider
        label="深度 Depth"
        value={config.depth}
        min={5}
        max={50}
        step={0.5}
        onChange={(v) => s.setDepth(v)}
        format={(v) => `${v.toFixed(1)} m`}
      />
      <Select
        label="地板模式 Floor"
        value={config.floorMode}
        options={[
          { value: 'grid', label: '网格 Grid' },
          { value: 'solid', label: '纯色 Solid' },
          { value: 'reflective', label: '反射 Reflective' }
        ]}
        onChange={(v) => s.setFloorMode(v)}
      />
      <ColorInput label="地板颜色 Floor" value={config.floorColor} onChange={(v) => s.setFloorColor(v)} />
      <ColorInput
        label="背景颜色 Background"
        value={config.backgroundColor}
        onChange={(v) => s.setBackgroundColor(v)}
      />
      <Toggle label="显示参考网格" value={config.showGrid} onChange={(v) => s.setShowGrid(v)} />

      <SectionTitle>灯光 / Lighting</SectionTitle>
      <Slider
        label="环境光 Ambient"
        value={light.ambientIntensity}
        min={0}
        max={1}
        onChange={(v) => s.setAmbientIntensity(v)}
      />
      <Slider
        label="背光 Rim"
        value={light.rimLightIntensity}
        min={0}
        max={1}
        onChange={(v) => s.setRimIntensity(v)}
      />
      {light.spotLights.map((sp, i) => (
        <Slider
          key={i}
          label={`聚光灯 ${i + 1} Spot ${i + 1}`}
          value={sp.intensity}
          min={0}
          max={6}
          onChange={(v) => s.setSpotIntensity(i, v)}
        />
      ))}
    </div>
  )
}
