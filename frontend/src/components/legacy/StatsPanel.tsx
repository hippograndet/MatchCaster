// frontend/src/components/StatsPanel.tsx
// SofaScore-style mirrored stat bars

import React from 'react'
import type { MatchState } from '../../utils/types'

interface StatsPanelProps {
  matchState: MatchState | null
}

interface StatRow {
  label: string
  homeVal: number
  awayVal: number
  format?: (v: number) => string
  highlight?: boolean
  absoluteBars?: boolean  // if true, each bar fills to its own % of 100 (not relative to each other)
}

const HOME_COLOR = '#22c55e'
const AWAY_COLOR = '#3b82f6'

function pct(val: number, total: number): number {
  return total === 0 ? 0 : Math.round((val / total) * 100)
}

export const StatsPanel: React.FC<StatsPanelProps> = ({ matchState }) => {
  if (!matchState) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="font-mono text-xs text-gray-600">Waiting for match…</p>
      </div>
    )
  }

  const { home_team, away_team, stats, possession } = matchState
  const h = stats[home_team]
  const a = stats[away_team]

  if (!h || !a) return null

  const homePos = possession[home_team] ?? 50
  const awayPos = possession[away_team] ?? 50

  const rows: StatRow[] = [
    {
      label: 'Shots',
      homeVal: h.shots,
      awayVal: a.shots,
    },
    {
      label: 'On Target',
      homeVal: h.shots_on_target,
      awayVal: a.shots_on_target,
    },
    {
      label: 'xG',
      homeVal: h.xg,
      awayVal: a.xg,
      format: (v) => v.toFixed(2),
    },
    {
      label: 'Passes',
      homeVal: h.passes_attempted,
      awayVal: a.passes_attempted,
    },
    {
      label: 'Pass Acc.',
      homeVal: h.passes_attempted > 0 ? pct(h.passes_completed, h.passes_attempted) : 0,
      awayVal: a.passes_attempted > 0 ? pct(a.passes_completed, a.passes_attempted) : 0,
      format: (v) => `${v}%`,
      absoluteBars: true,
    },
    {
      label: 'Fouls',
      homeVal: h.fouls,
      awayVal: a.fouls,
    },
    {
      label: 'Yellow Cards',
      homeVal: h.yellow_cards,
      awayVal: a.yellow_cards,
    },
    {
      label: 'Red Cards',
      homeVal: h.red_cards,
      awayVal: a.red_cards,
    },
  ]

  return (
    <div className="flex flex-col gap-1 px-3 py-2 overflow-y-auto h-full">
      {/* Possession bar */}
      <div className="mb-3">
        <div className="flex justify-between items-center mb-1">
          <span className="font-mono text-sm font-bold" style={{ color: HOME_COLOR }}>
            {homePos.toFixed(0)}%
          </span>
          <span className="font-mono text-[10px] text-gray-500 uppercase tracking-widest">
            Ball Possession
          </span>
          <span className="font-mono text-sm font-bold" style={{ color: AWAY_COLOR }}>
            {awayPos.toFixed(0)}%
          </span>
        </div>
        <div className="flex h-2 rounded-full overflow-hidden">
          <div
            className="transition-all duration-700"
            style={{ width: `${homePos}%`, backgroundColor: HOME_COLOR }}
          />
          <div
            className="transition-all duration-700"
            style={{ width: `${awayPos}%`, backgroundColor: AWAY_COLOR }}
          />
        </div>
      </div>

      {/* Stat rows */}
      {rows.map((row) => {
        const total = row.homeVal + row.awayVal
        // absoluteBars: each bar fills to its own value as a % of 100
        const homePct = row.absoluteBars ? row.homeVal : (total === 0 ? 50 : (row.homeVal / total) * 100)
        const awayPct = row.absoluteBars ? row.awayVal : (total === 0 ? 50 : (row.awayVal / total) * 100)
        const fmt = row.format ?? ((v) => String(v))

        return (
          <div key={row.label} className="mb-2">
            {/* Numbers + label */}
            <div className="flex items-center justify-between text-xs mb-0.5">
              <span className="font-mono font-semibold text-gray-200 w-8 text-right">
                {fmt(row.homeVal)}
              </span>
              <span className="text-gray-500 text-[10px] uppercase tracking-widest flex-1 text-center">
                {row.label}
              </span>
              <span className="font-mono font-semibold text-gray-200 w-8 text-left">
                {fmt(row.awayVal)}
              </span>
            </div>
            {/* Bars */}
            <div className="flex gap-0.5 h-1.5">
              {/* Home bar — grows from RIGHT to left */}
              <div className="flex-1 flex justify-end rounded-l overflow-hidden bg-[#1a1a28]">
                <div
                  className="h-full rounded-l transition-all duration-700"
                  style={{
                    width: `${homePct}%`,
                    backgroundColor: HOME_COLOR,
                    opacity: 0.85,
                  }}
                />
              </div>
              {/* Away bar — grows from LEFT to right */}
              <div className="flex-1 flex justify-start rounded-r overflow-hidden bg-[#1a1a28]">
                <div
                  className="h-full rounded-r transition-all duration-700"
                  style={{
                    width: `${awayPct}%`,
                    backgroundColor: AWAY_COLOR,
                    opacity: 0.85,
                  }}
                />
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
