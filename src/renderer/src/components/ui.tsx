import type { ReactNode } from 'react'

export function Field({ label, children }: { label: string; children: ReactNode }): React.JSX.Element {
  return (
    <label className="mb-2 block">
      <div className="mb-1 text-xs text-zinc-400">{label}</div>
      {children}
    </label>
  )
}

export function Slider({
  label,
  value,
  min,
  max,
  step = 0.01,
  onChange,
  format
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
  format?: (v: number) => string
}): React.JSX.Element {
  return (
    <div className="mb-2">
      <div className="mb-1 flex justify-between text-xs text-zinc-400">
        <span>{label}</span>
        <span className="text-zinc-300">{format ? format(value) : value.toFixed(2)}</span>
      </div>
      <input
        type="range"
        className="w-full"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
    </div>
  )
}

export function ColorInput({
  label,
  value,
  onChange
}: {
  label: string
  value: string
  onChange: (v: string) => void
}): React.JSX.Element {
  return (
    <div className="mb-2 flex items-center justify-between">
      <span className="text-xs text-zinc-400">{label}</span>
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-6 w-10 cursor-pointer rounded border border-zinc-700 bg-transparent"
      />
    </div>
  )
}

export function Select<T extends string>({
  label,
  value,
  options,
  onChange
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}): React.JSX.Element {
  return (
    <div className="mb-2">
      <div className="mb-1 text-xs text-zinc-400">{label}</div>
      <select
        className="w-full rounded bg-zinc-800 px-2 py-1 text-sm outline-none"
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}

export function Toggle({
  label,
  value,
  onChange,
  disabled = false,
  hint
}: {
  label: string
  value: boolean
  onChange: (v: boolean) => void
  /** Greys the row out and blocks input — use when the setting has no effect. */
  disabled?: boolean
  /** Tooltip explaining why it is unavailable. */
  hint?: string
}): React.JSX.Element {
  return (
    <label
      title={hint}
      className={
        'mb-2 flex items-center justify-between ' +
        (disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer')
      }
    >
      <span className="text-xs text-zinc-400">{label}</span>
      <input
        type="checkbox"
        checked={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-blue-500 disabled:cursor-not-allowed"
      />
    </label>
  )
}

export function Button({
  children,
  onClick,
  variant = 'default',
  disabled
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'default' | 'primary'
  disabled?: boolean
}): React.JSX.Element {
  const cls =
    variant === 'primary'
      ? 'bg-blue-600 text-white hover:bg-blue-500'
      : 'bg-zinc-800 text-zinc-200 hover:bg-zinc-700'
  return (
    <button
      className={`rounded px-2 py-1 text-xs ${cls} disabled:opacity-50`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  )
}

export function SectionTitle({ children }: { children: ReactNode }): React.JSX.Element {
  return <div className="mb-2 mt-3 border-b border-zinc-800 pb-1 text-xs font-semibold text-zinc-300">{children}</div>
}
