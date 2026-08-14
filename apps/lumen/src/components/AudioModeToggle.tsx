import {
  saveAudioMode,
  type AudioMode,
} from '../lib/audioMode'

type Props = {
  value: AudioMode
  onChange: (mode: AudioMode) => void
  className?: string
  compact?: boolean
}

const OPTIONS: { id: AudioMode; label: string }[] = [
  { id: 'sub', label: 'Sub' },
  { id: 'dub', label: 'Dub' },
  { id: 'any', label: 'Any' },
]

export function AudioModeToggle({ value, onChange, className, compact }: Props) {
  return (
    <div
      className={['demo-audio-mode', compact ? 'is-compact' : '', className].filter(Boolean).join(' ')}
      role="group"
      aria-label="Audio preference"
    >
      {compact ? null : <span className="demo-audio-mode-label">Audio</span>}
      <div className="demo-audio-mode-btns">
        {OPTIONS.map((opt) => (
          <button
            key={opt.id}
            type="button"
            className={value === opt.id ? 'is-active' : undefined}
            aria-pressed={value === opt.id}
            onClick={() => {
              saveAudioMode(opt.id)
              onChange(opt.id)
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}
