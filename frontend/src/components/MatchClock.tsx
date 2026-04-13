// frontend/src/components/MatchClock.tsx
// Displays the current match clock and score.

import React from 'react'

interface MatchClockProps {
  matchTime: number   // seconds
  score: { home: number; away: number }
  homeTeam: string
  awayTeam: string
  running: boolean
}

function formatTime(seconds: number): string {
  const totalMinutes = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${String(totalMinutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function shortTeamName(name: string): string {
  if (!name) return '???'
  // Take first 3 chars of each word for long names, or full if short
  if (name.length <= 10) return name
  const words = name.split(' ')
  if (words.length >= 2) {
    return words.map(w => w.slice(0, 3)).join(' ')
  }
  return name.slice(0, 10)
}

export const MatchClock: React.FC<MatchClockProps> = ({
  matchTime,
  score,
  homeTeam,
  awayTeam,
  running,
}) => {
  const period = matchTime < 45 * 60 ? '1st Half' : matchTime < 90 * 60 ? '2nd Half' : 'ET'

  return (
    <div className="flex items-center gap-4">
      {/* Home team + score */}
      <div className="flex items-center gap-2">
        <span className="font-sans text-sm text-gray-300 truncate max-w-[120px]">
          {homeTeam || 'Home'}
        </span>
        <span className="font-mono text-xl font-bold text-white">
          {score.home}
        </span>
      </div>

      {/* Clock */}
      <div className="flex flex-col items-center">
        <div
          className={`font-mono text-lg font-bold px-3 py-1 rounded bg-[#1c1c26] border border-[#2d2d3d] ${
            running ? 'text-white' : 'text-gray-500'
          }`}
        >
          {formatTime(matchTime)}
        </div>
        <span className="text-xs text-gray-500 mt-0.5 font-mono">{period}</span>
      </div>

      {/* Away team + score */}
      <div className="flex items-center gap-2">
        <span className="font-mono text-xl font-bold text-white">
          {score.away}
        </span>
        <span className="font-sans text-sm text-gray-300 truncate max-w-[120px]">
          {awayTeam || 'Away'}
        </span>
      </div>
    </div>
  )
}
