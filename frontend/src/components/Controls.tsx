// frontend/src/components/Controls.tsx

import React, { useEffect, useState } from 'react'
import type { MatchInfo, Personality, PitchView, HeatmapTeam } from '../utils/types'

interface ControlsProps {
  running: boolean
  speed: number
  connected: boolean
  selectedMatch: string | null
  pitchView: PitchView
  heatmapTeam: HeatmapTeam
  heatmapGranularity: number
  personality: Personality
  matchEnded: boolean
  homeTeam: string
  awayTeam: string
  onPlay: () => void
  onPause: () => void
  onRewind: () => void
  onSpeedChange: (speed: number) => void
  onMatchSelect: (matchId: string) => void
  onPitchViewChange: (v: PitchView) => void
  onHeatmapTeamChange: (t: HeatmapTeam) => void
  onHeatmapGranularityChange: (g: number) => void
  onPersonalityChange: (p: Personality) => void
  muted: boolean
  onMuteToggle: () => void
}

const PERSONALITIES: { value: Personality; label: string }[] = [
  { value: 'neutral',      label: '🎙 Neutral' },
  { value: 'enthusiastic', label: '🔥 Enthusiastic' },
  { value: 'analytical',   label: '📐 Analytical' },
  { value: 'home_bias',    label: '🏠 Home Bias' },
  { value: 'away_bias',    label: '✈️ Away Bias' },
]

const PITCH_VIEWS: { value: PitchView; label: string }[] = [
  { value: 'pitch',     label: 'Live' },
  { value: 'formation', label: 'Formation' },
  { value: 'heatmap',   label: 'Heatmap' },
  { value: 'shotmap',   label: 'Shots' },
  { value: 'vectors',   label: 'Build-up' },
]

export const Controls: React.FC<ControlsProps> = ({
  running,
  speed,
  connected,
  selectedMatch,
  pitchView,
  heatmapTeam,
  heatmapGranularity,
  personality,
  matchEnded,
  homeTeam,
  awayTeam,
  onPlay,
  onPause,
  onRewind,
  onSpeedChange,
  onMatchSelect,
  onPitchViewChange,
  onHeatmapTeamChange,
  onHeatmapGranularityChange,
  onPersonalityChange,
  muted,
  onMuteToggle,
}) => {
  const [matches, setMatches] = useState<MatchInfo[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetch('/api/matches')
      .then(r => r.json())
      .then((data: MatchInfo[]) => { setMatches(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const formatMatchLabel = (m: MatchInfo): string =>
    m.teams.length >= 2 ? `${m.teams[0]} vs ${m.teams[1]}` : `Match ${m.match_id}`

  const canInteract = connected && !!selectedMatch && !matchEnded

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Play/Pause */}
      <button
        onClick={running ? onPause : onPlay}
        disabled={!connected || !selectedMatch || matchEnded}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded font-mono text-sm font-medium
          transition-all disabled:opacity-40 disabled:cursor-not-allowed
          ${running
            ? 'bg-amber-500 text-black hover:bg-amber-400'
            : 'bg-[#1c1c26] border border-[#2d2d3d] text-gray-300 hover:border-amber-500/50'
          }`}
      >
        {running ? (
          <><svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" />
          </svg>Pause</>
        ) : matchEnded ? (
          'Match Over'
        ) : (
          <><svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <polygon points="5,3 19,12 5,21" />
          </svg>Play</>
        )}
      </button>

      {/* Rewind 30s */}
      <button
        onClick={onRewind}
        disabled={!canInteract}
        title="Rewind 30 seconds"
        className="flex items-center gap-1 px-2 py-1.5 rounded font-mono text-xs border border-[#2d2d3d]
          text-gray-400 hover:text-gray-200 hover:border-amber-500/40 transition-all
          disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
          <text x="9" y="16" fontSize="6" fill="currentColor" fontFamily="monospace">30</text>
        </svg>
        −30s
      </button>

      {/* Speed — discrete values only */}
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs text-gray-500 hidden sm:block">Speed:</span>
        <div className="flex rounded overflow-hidden border border-[#2d2d3d]">
          {[0.5, 1, 2, 4, 8].map(v => (
            <button
              key={v}
              onClick={() => onSpeedChange(v)}
              disabled={!canInteract}
              className={`px-2 py-1 font-mono text-xs transition-colors disabled:opacity-40
                ${speed === v
                  ? 'bg-amber-500/25 text-amber-400'
                  : 'text-gray-500 hover:text-gray-300'}`}
            >
              {v}×
            </button>
          ))}
        </div>
      </div>

      {/* Pitch view tabs */}
      <div className="flex rounded overflow-hidden border border-[#2d2d3d]">
        {PITCH_VIEWS.map(v => (
          <button
            key={v.value}
            onClick={() => onPitchViewChange(v.value)}
            className={`px-2.5 py-1 font-mono text-xs transition-colors ${
              pitchView === v.value
                ? 'bg-amber-500/20 text-amber-400'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* Heatmap controls — only visible when heatmap view is active */}
      {pitchView === 'heatmap' && (
        <>
          {/* Team toggle */}
          <div className="flex rounded overflow-hidden border border-[#2d2d3d]">
            {(['home', 'away'] as const).map(t => (
              <button
                key={t}
                onClick={() => onHeatmapTeamChange(t)}
                className={`px-2.5 py-1 font-mono text-xs transition-colors ${
                  heatmapTeam === t
                    ? 'bg-blue-500/25 text-blue-300'
                    : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {t === 'home' ? (homeTeam || 'Home') : (awayTeam || 'Away')}
              </button>
            ))}
          </div>
          {/* Granularity slider */}
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs text-gray-500">Detail:</span>
            <input
              type="range"
              min={1}
              max={6}
              step={1}
              value={heatmapGranularity}
              onChange={e => onHeatmapGranularityChange(Number(e.target.value))}
              className="w-16 accent-blue-400"
              title={`Granularity: ${Math.pow(2, heatmapGranularity)} zones/axis`}
            />
            <span className="font-mono text-[10px] text-gray-600">
              {Math.pow(2, heatmapGranularity)}²
            </span>
          </div>
        </>
      )}

      {/* Personality */}
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs text-gray-500 hidden sm:block">Voice:</span>
        <select
          value={personality}
          onChange={e => onPersonalityChange(e.target.value as Personality)}
          className="bg-[#1c1c26] border border-[#2d2d3d] rounded px-2 py-1 text-xs text-gray-300
            focus:outline-none focus:border-amber-500/50"
        >
          {PERSONALITIES.map(p => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </div>

      {/* Match selector */}
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs text-gray-500 hidden sm:block">Match:</span>
        <select
          value={selectedMatch ?? ''}
          onChange={e => onMatchSelect(e.target.value)}
          disabled={loading}
          className="bg-[#1c1c26] border border-[#2d2d3d] rounded px-2 py-1.5 text-sm text-gray-200
            focus:outline-none focus:border-amber-500/50 disabled:opacity-40 max-w-[200px]"
        >
          <option value="">
            {loading ? 'Loading…' : matches.length === 0 ? 'No matches found' : 'Select match…'}
          </option>
          {matches.map(m => (
            <option key={m.match_id} value={m.match_id}>{formatMatchLabel(m)}</option>
          ))}
        </select>
      </div>

      {/* Mute */}
      <button
        onClick={onMuteToggle}
        className={`p-1.5 rounded border transition-all ${
          muted ? 'border-red-500/50 text-red-400 bg-red-900/20'
                : 'border-[#2d2d3d] text-gray-400 hover:text-gray-200'
        }`}
        title={muted ? 'Unmute' : 'Mute'}
      >
        {muted ? '🔇' : '🔊'}
      </button>

      {/* Connection dot */}
      <div className="flex items-center gap-1 ml-auto">
        <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />
        <span className="font-mono text-[10px] text-gray-600">{connected ? 'Live' : 'Off'}</span>
      </div>
    </div>
  )
}
