import { useState } from 'react'
import {
  ANIME4K_PRESETS,
  ANIME4K_WORKGROUPS,
  DEFAULT_ANIME4K_SETTINGS,
  anime4kUnsupportedReason,
  isAnime4KSupported,
  type Anime4KPreset,
  type Anime4KSettings,
  type Anime4KWorkgroup,
} from '../lib/anime4k'

export type VideoFilterSettings = {
  brightness: number
  contrast: number
  saturation: number
}

export const DEFAULT_VIDEO_FILTERS: VideoFilterSettings = {
  brightness: 100,
  contrast: 100,
  saturation: 100,
}

type Tab = 'filters' | 'anime4k'

type Props = {
  open: boolean
  onClose: () => void
  enabled: boolean
  onEnabledChange: (on: boolean) => void
  settings: Anime4KSettings
  onSettingsChange: (next: Anime4KSettings) => void
  filters: VideoFilterSettings
  onFiltersChange: (next: VideoFilterSettings) => void
  busy?: boolean
  error?: string | null
}

export function VideoProcessingPanel({
  open,
  onClose,
  enabled,
  onEnabledChange,
  settings,
  onSettingsChange,
  filters,
  onFiltersChange,
  busy,
  error,
}: Props) {
  const [tab, setTab] = useState<Tab>('anime4k')

  if (!open) return null

  const setPreset = (preset: Anime4KPreset) => {
    onSettingsChange({ ...settings, preset })
    if (!enabled) onEnabledChange(true)
  }

  const setWorkgroup = (workgroup: Anime4KWorkgroup) => {
    const meta = ANIME4K_WORKGROUPS.find((w) => w.id === workgroup)
    if (!meta?.supported) return
    onSettingsChange({ ...settings, workgroup })
  }

  return (
    <div
      className="vp-panel"
      role="dialog"
      aria-modal="true"
      aria-label="Video Processing"
      onClick={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div className="vp-panel-head">
        <h3 className="vp-panel-title">Video Processing</h3>
        <button type="button" className="vp-panel-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>

      <div className="vp-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'filters'}
          className={tab === 'filters' ? 'is-active' : undefined}
          onClick={() => setTab('filters')}
        >
          Filters
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'anime4k'}
          className={tab === 'anime4k' ? 'is-active' : undefined}
          onClick={() => setTab('anime4k')}
        >
          <span className="vp-tab-icon" aria-hidden>
            ∿
          </span>
          Anime4K
        </button>
      </div>

      <div className="vp-panel-body">
        {tab === 'filters' ? (
          <div className="vp-section">
            <p className="vp-section-label">Picture</p>
            <FilterSlider
              label="Brightness"
              value={filters.brightness}
              onChange={(brightness) => onFiltersChange({ ...filters, brightness })}
            />
            <FilterSlider
              label="Contrast"
              value={filters.contrast}
              onChange={(contrast) => onFiltersChange({ ...filters, contrast })}
            />
            <FilterSlider
              label="Saturation"
              value={filters.saturation}
              onChange={(saturation) => onFiltersChange({ ...filters, saturation })}
            />
            <button
              type="button"
              className="vp-reset"
              onClick={() => onFiltersChange({ ...DEFAULT_VIDEO_FILTERS })}
            >
              <span aria-hidden>↺</span> Reset Filters
            </button>
          </div>
        ) : (
          <>
            <div className="vp-enable-row">
              <div>
                <p className="vp-enable-title">Anime4K upscale</p>
                <p className="vp-enable-hint">
                  {isAnime4KSupported()
                    ? 'Real-time WebGPU restore + upscale'
                    : anime4kUnsupportedReason() || 'WebGPU unavailable'}
                </p>
              </div>
              <button
                type="button"
                className={['vp-switch', enabled ? 'is-on' : ''].filter(Boolean).join(' ')}
                role="switch"
                aria-checked={enabled}
                disabled={busy || !isAnime4KSupported()}
                onClick={() => onEnabledChange(!enabled)}
              >
                <span className="vp-switch-knob" />
              </button>
            </div>

            {error ? <p className="vp-error">{error}</p> : null}

            <div className="vp-section">
              <p className="vp-section-label">Preset</p>
              <div className="vp-preset-grid">
                {ANIME4K_PRESETS.map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    className={[
                      'vp-choice',
                      settings.preset === preset.id ? 'is-active' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={() => setPreset(preset.id)}
                  >
                    <span className="vp-choice-title">{preset.title}</span>
                    <span className="vp-choice-sub">{preset.subtitle}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="vp-section">
              <p className="vp-section-label">Line effects (optional)</p>
              <button
                type="button"
                className={[
                  'vp-choice vp-choice-wide',
                  settings.darkenLines ? 'is-active' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() =>
                  onSettingsChange({ ...settings, darkenLines: !settings.darkenLines })
                }
              >
                <span className="vp-choice-title">Darken Lines</span>
                <span className="vp-choice-sub">Makes outlines bolder</span>
              </button>
              <button
                type="button"
                className={[
                  'vp-choice vp-choice-wide',
                  settings.thinLines ? 'is-active' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() =>
                  onSettingsChange({ ...settings, thinLines: !settings.thinLines })
                }
              >
                <span className="vp-choice-title">Thin Lines</span>
                <span className="vp-choice-sub">Refines line weight</span>
              </button>
              <p className="vp-caption">
                Anime4K Darken_HQ / Thin_HQ — applied after the preset. Thin runs before Darken.
              </p>
            </div>

            <div className="vp-section">
              <div className="vp-section-row">
                <p className="vp-section-label">Performance</p>
                <span className="vp-section-value">{settings.workgroup}</span>
              </div>
              <p className="vp-field-label">Workgroup Size</p>
              <div className="vp-workgroup-row">
                {ANIME4K_WORKGROUPS.map((wg) => (
                  <button
                    key={wg.id}
                    type="button"
                    disabled={!wg.supported}
                    title={
                      wg.supported
                        ? undefined
                        : 'Preset CNN shaders from anime4k-webgpu are compiled at 8×8'
                    }
                    className={[
                      'vp-choice',
                      settings.workgroup === wg.id ? 'is-active' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={() => setWorkgroup(wg.id)}
                  >
                    <span className="vp-choice-title">{wg.title}</span>
                    <span className="vp-choice-sub">{wg.subtitle}</span>
                  </button>
                ))}
              </div>
              <p className="vp-caption">
                Mode presets ship with fixed 8×8 workgroups. Line-effect shaders also use 8×8.
              </p>
            </div>

            <button
              type="button"
              className="vp-reset"
              onClick={() => onSettingsChange({ ...DEFAULT_ANIME4K_SETTINGS })}
            >
              <span aria-hidden>↺</span> Reset Upscaler Settings
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function FilterSlider({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (v: number) => void
}) {
  return (
    <label className="vp-slider">
      <span className="vp-slider-head">
        <span>{label}</span>
        <span>{value}%</span>
      </span>
      <input
        type="range"
        min={50}
        max={150}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}
