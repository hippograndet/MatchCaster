// frontend/src/components/OverlayPanel.tsx
// Floating panel for pitch overlay settings — each overlay independently toggleable

import React, { useEffect, useRef } from 'react'
import type { PitchOverlays, HeatmapTeam, Personality } from '../utils/types'

interface OverlayPanelProps {
  isOpen: boolean
  overlays: PitchOverlays
  heatmapTeam: HeatmapTeam
  heatmapGranularity: number
  personality: Personality
  homeTeam: string
  awayTeam: string
  onClose: () => void
  onToggleOverlay: (key: keyof PitchOverlays) => void
  onHeatmapTeamChange: (t: HeatmapTeam) => void
  onHeatmapGranularityChange: (g: number) => void
  onPersonalityChange: (p: Personality) => void
}

const OVERLAY_DEFS: { key: keyof PitchOverlays; label: string; icon: string }[] = [
  { key: 'live',      label: 'Live',      icon: '⚽' },
  { key: 'formation', label: 'Formation', icon: '🔷' },
  { key: 'heatmap',   label: 'Heatmap',   icon: '🔥' },
  { key: 'shotmap',   label: 'Shots',     icon: '🎯' },
  { key: 'vectors',   label: 'Build-up',  icon: '↗' },
]

const PERSONALITIES: { value: Personality; icon: string; label: string }[] = [
  { value: 'neutral',      icon: '🎙', label: 'Neutral' },
  { value: 'enthusiastic', icon: '🔥', label: 'Enthusiastic' },
  { value: 'analytical',   icon: '📐', label: 'Analytical' },
  { value: 'home_bias',    icon: '🏠', label: 'Home Fan' },
  { value: 'away_bias',    icon: '✈️', label: 'Away Fan' },
]

export const OverlayPanel: React.FC<OverlayPanelProps> = ({
  isOpen, overlays, heatmapTeam, heatmapGranularity, personality,
  homeTeam, awayTeam, onClose,
  onToggleOverlay, onHeatmapTeamChange, onHeatmapGranularityChange, onPersonalityChange,
}) => {
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    setTimeout(() => document.addEventListener('mousedown', handler), 0)
    return () => document.removeEventListener('mousedown', handler)
  }, [isOpen, onClose])

  return (
    <div
      ref={panelRef}
      className={`absolute top-3 right-3 z-20 w-64 bg-[#0d0d18]/95 backdrop-blur-sm
        border border-[#252535] rounded-2xl shadow-2xl
        transition-all duration-200 origin-top-right
        ${isOpen ? 'opacity-100 scale-100 pointer-events-auto' : 'opacity-0 scale-95 pointer-events-none'}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#1a1a28]">
        <span className="font-mono text-[11px] text-gray-400 uppercase tracking-wider">View Settings</span>
        <button
          onClick={onClose}
          className="w-6 h-6 flex items-center justify-center rounded-full text-gray-600
            hover:text-gray-300 hover:bg-[#1a1a28] transition-all text-sm"
        >
          ✕
        </button>
      </div>

      <div className="p-4 space-y-5">
        {/* Overlay toggles — multi-select */}
        <div>
          <p className="font-mono text-[10px] text-gray-600 uppercase tracking-widest mb-2">
            Overlays <span className="text-gray-700 normal-case tracking-normal">(combine freely)</span>
          </p>
          <div className="grid grid-cols-5 gap-1">
            {OVERLAY_DEFS.map(({ key, label, icon }) => {
              const active = overlays[key]
              return (
                <button
                  key={key}
                  onClick={() => onToggleOverlay(key)}
                  title={label}
                  className={`flex flex-col items-center gap-1 py-2 rounded-lg border text-[10px] font-mono
                    transition-all relative
                    ${active
                      ? 'border-amber-500/60 bg-amber-500/10 text-amber-300'
                      : 'border-[#1e1e30] bg-[#111118] text-gray-500 hover:border-[#2a2a3a] hover:text-gray-300'
                    }`}
                >
                  <span className="text-base leading-none">{icon}</span>
                  <span className="leading-none">{label}</span>
                  {active && (
                    <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-amber-400" />
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* Heatmap settings — only when heatmap overlay is active */}
        {overlays.heatmap && (
          <div className="space-y-3 pt-1 border-t border-[#1a1a28]">
            <p className="font-mono text-[10px] text-gray-600 uppercase tracking-widest">Heatmap</p>

            {/* Team toggle */}
            <div className="flex rounded-lg border border-[#1e1e30] overflow-hidden">
              {(['home', 'away'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => onHeatmapTeamChange(t)}
                  className={`flex-1 py-1.5 text-xs font-mono transition-colors
                    ${heatmapTeam === t
                      ? 'bg-blue-600/30 text-blue-300'
                      : 'text-gray-500 hover:text-gray-300'
                    }`}
                >
                  {t === 'home' ? (homeTeam || 'Home') : (awayTeam || 'Away')}
                </button>
              ))}
            </div>

            {/* Granularity */}
            <div className="flex items-center gap-3">
              <span className="font-mono text-[10px] text-gray-600 flex-shrink-0">Detail</span>
              <input
                type="range" min={1} max={6} step={1}
                value={heatmapGranularity}
                onChange={e => onHeatmapGranularityChange(Number(e.target.value))}
                className="flex-1 accent-blue-400 h-1"
              />
              <span className="font-mono text-[10px] text-gray-500 w-8 text-right tabular-nums">
                {Math.pow(2, heatmapGranularity)}²
              </span>
            </div>
          </div>
        )}

        {/* Commentary voice */}
        <div className="pt-1 border-t border-[#1a1a28]">
          <p className="font-mono text-[10px] text-gray-600 uppercase tracking-widest mb-2">Voice</p>
          <div className="grid grid-cols-5 gap-1">
            {PERSONALITIES.map(p => (
              <button
                key={p.value}
                onClick={() => onPersonalityChange(p.value)}
                title={p.label}
                className={`flex flex-col items-center gap-1 py-2 rounded-lg border text-[10px] font-mono
                  transition-all
                  ${personality === p.value
                    ? 'border-amber-500/60 bg-amber-500/10 text-amber-300'
                    : 'border-[#1e1e30] bg-[#111118] text-gray-500 hover:border-[#2a2a3a] hover:text-gray-300'
                  }`}
              >
                <span className="text-base leading-none">{p.icon}</span>
                <span className="leading-none truncate w-full text-center">{p.label.split(' ')[0]}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
