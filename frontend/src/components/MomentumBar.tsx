// frontend/src/components/MomentumBar.tsx
// Real-time momentum indicator driven by backend pattern analysis.

import React from 'react'
import type { MatchAnalysis } from '../utils/types'

interface MomentumBarProps {
  homeTeam: string
  awayTeam: string
  analysis: MatchAnalysis | null
}

const HOME_COLOR = '#22c55e'
const AWAY_COLOR = '#3b82f6'

export const MomentumBar: React.FC<MomentumBarProps> = ({ homeTeam, awayTeam, analysis }) => {
  if (!analysis) return null

  const home = analysis.momentum_home
  const away = analysis.momentum_away
  const hxg  = analysis.xg_home
  const axg  = analysis.xg_away
  const hEntry = analysis.dangerous_entries[homeTeam] ?? 0
  const aEntry = analysis.dangerous_entries[awayTeam] ?? 0

  // Momentum bar description
  let label = 'Even'
  if (home > away + 20) label = `${homeTeam} dominant`
  else if (away > home + 20) label = `${awayTeam} dominant`
  else if (home > away + 8) label = `${homeTeam} edging`
  else if (away > home + 8) label = `${awayTeam} edging`

  return (
    <div className="px-3 py-2 border-b border-[#1c1c26]">
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-[10px] text-gray-600 uppercase tracking-widest">Momentum</span>
        <span className="font-mono text-[10px] text-gray-500">{label}</span>
      </div>

      {/* Momentum bar */}
      <div className="flex h-2 rounded-full overflow-hidden mb-2">
        <div
          className="transition-all duration-1000"
          style={{ width: `${home}%`, backgroundColor: HOME_COLOR, opacity: 0.85 }}
        />
        <div
          className="transition-all duration-1000"
          style={{ width: `${away}%`, backgroundColor: AWAY_COLOR, opacity: 0.85 }}
        />
      </div>

      {/* Mini stats row */}
      <div className="flex items-center justify-between text-[10px] font-mono">
        <span style={{ color: HOME_COLOR }}>{home.toFixed(0)}%</span>
        <div className="flex gap-3 text-gray-600">
          <span title="Expected Goals">xG {hxg.toFixed(2)} – {axg.toFixed(2)}</span>
          <span title="Box entries">⬛ {hEntry} – {aEntry}</span>
        </div>
        <span style={{ color: AWAY_COLOR }}>{away.toFixed(0)}%</span>
      </div>
    </div>
  )
}
