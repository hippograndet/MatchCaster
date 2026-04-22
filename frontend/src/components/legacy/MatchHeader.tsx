// frontend/src/components/MatchHeader.tsx
// SofaScore-inspired match header: teams, score, status, goal scorers, meta

import React from 'react'
import type { GoalEvent, MatchMeta } from '../../utils/types'

interface MatchHeaderProps {
  homeTeam: string
  awayTeam: string
  score: { home: number; away: number }
  matchTime: number
  displayTime: number
  running: boolean
  matchEnded: boolean
  goalEvents: GoalEvent[]
  matchMeta: MatchMeta | null
  homeColor: string
  awayColor: string
}

/** Format seconds → mm'ss" */
function fmtClock(sec: number): string {
  const min = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${min}'${String(s).padStart(2, '0')}"`
}

/** Format "Firstname Lastname" → "F. Lastname" */
function shortName(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return name
  return `${parts[0][0]}. ${parts.slice(1).join(' ')}`
}

export const MatchHeader: React.FC<MatchHeaderProps> = ({
  homeTeam, awayTeam, score, matchTime, displayTime, running, matchEnded,
  goalEvents, matchMeta, homeColor, awayColor,
}) => {
  const homeGoals = goalEvents.filter(g => g.team === homeTeam)
  const awayGoals = goalEvents.filter(g => g.team === awayTeam)

  // Status badge: always show time when not at zero; never show "HT"
  const statusLabel = matchEnded
    ? 'FT'
    : matchTime === 0
    ? 'Pre-match'
    : fmtClock(displayTime)

  // Meta line: competition + venue
  const metaParts: string[] = []
  if (matchMeta?.competition) metaParts.push(matchMeta.competition)
  if (matchMeta?.date) metaParts.push(matchMeta.date)

  const venueParts: string[] = []
  if (matchMeta?.stadium) venueParts.push(matchMeta.stadium)
  if (matchMeta?.city) venueParts.push(matchMeta.city)
  if (matchMeta?.country) venueParts.push(matchMeta.country)
  const venueStr = venueParts.join(', ')
  if (venueStr) metaParts.push(venueStr)
  if (matchMeta?.weather) metaParts.push(matchMeta.weather)

  return (
    <div className="flex-shrink-0 bg-[#0a0a12] border-b border-[#1e1e2e]">
      {/* Competition / venue strip */}
      {metaParts.length > 0 && (
        <div className="text-center py-1.5 border-b border-[#131320] bg-[#080810]">
          <span className="font-mono text-[10px] text-gray-600 tracking-wider">
            {metaParts.join('  ·  ')}
          </span>
        </div>
      )}

      {/* Main score row */}
      <div className="flex items-stretch justify-between px-4 py-4 gap-4">

        {/* Home team */}
        <div className="flex-1 flex flex-col items-end justify-center gap-1.5 min-w-0">
          <h2
            className="font-sans font-bold text-lg sm:text-xl leading-tight text-right truncate max-w-full"
            style={{ color: homeColor }}
          >
            {homeTeam}
          </h2>
          {/* Goal scorers */}
          <div className="flex flex-col items-end gap-0.5">
            {homeGoals.map((g, i) => (
              <span key={i} className="font-mono text-[10px] text-gray-400">
                {shortName(g.player)} {g.minute}'
                {g.is_own_goal && <span className="text-red-400 ml-1">(og)</span>}
              </span>
            ))}
          </div>
        </div>

        {/* Score + status */}
        <div className="flex flex-col items-center justify-center flex-shrink-0 gap-2">
          {/* Score */}
          <div className="flex items-center gap-2">
            <span className="font-mono font-black text-4xl sm:text-5xl text-white tabular-nums leading-none">
              {score.home}
            </span>
            <span className="font-mono text-gray-600 text-2xl leading-none">–</span>
            <span className="font-mono font-black text-4xl sm:text-5xl text-white tabular-nums leading-none">
              {score.away}
            </span>
          </div>

          {/* Status badge */}
          <div
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-mono font-semibold
              ${matchEnded
                ? 'bg-gray-800 text-gray-400'
                : running
                ? 'bg-emerald-900/50 text-emerald-300 border border-emerald-700/40'
                : matchTime === 0
                ? 'bg-[#1a1a2c] text-gray-500 border border-[#252535]'
                : 'bg-[#1a1a2c] text-gray-300 border border-[#252535]'
              }`}
          >
            {running && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
            )}
            {statusLabel}
          </div>
        </div>

        {/* Away team */}
        <div className="flex-1 flex flex-col items-start justify-center gap-1.5 min-w-0">
          <h2
            className="font-sans font-bold text-lg sm:text-xl leading-tight truncate max-w-full"
            style={{ color: awayColor }}
          >
            {awayTeam}
          </h2>
          {/* Goal scorers */}
          <div className="flex flex-col items-start gap-0.5">
            {awayGoals.map((g, i) => (
              <span key={i} className="font-mono text-[10px] text-gray-400">
                {shortName(g.player)} {g.minute}'
                {g.is_own_goal && <span className="text-red-400 ml-1">(og)</span>}
              </span>
            ))}
          </div>
        </div>

      </div>
    </div>
  )
}
