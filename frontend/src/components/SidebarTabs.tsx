// frontend/src/components/SidebarTabs.tsx
// Tabbed right sidebar: compact score header + Stats | Live | Squad

import React, { useEffect, useRef, useState } from 'react'
import type { MatchState, MatchEventData, MatchAnalysis, LineupPlayer, GoalEvent, MatchMeta } from '../utils/types'

type Tab = 'stats' | 'live' | 'squad'

interface SidebarTabsProps {
  matchState: MatchState | null
  recentEvents: MatchEventData[]
  analysis: MatchAnalysis | null
  lineup: LineupPlayer[]
  homeTeam: string
  awayTeam: string
  homeColor: string
  awayColor: string
  // Score panel props
  score: { home: number; away: number }
  matchTime: number
  running: boolean
  matchEnded: boolean
  currentPeriod: number
  goalEvents: GoalEvent[]
  matchMeta: MatchMeta | null
}

// ── Helpers ────────────────────────────────────────────────────────────────

function pct(val: number, total: number): number {
  return total === 0 ? 0 : Math.round((val / total) * 100)
}

function fmtMin(sec: number): string {
  return `${Math.floor(sec / 60)}'`
}

function fmtClock(sec: number, period: number): string {
  const min = Math.floor(Math.max(0, sec) / 60)
  const halfEnd: Record<number, number> = { 1: 45, 2: 90, 3: 105, 4: 120 }
  const cap = halfEnd[period] ?? 90
  return min <= cap ? `${min}'` : `${cap}+${min - cap}'`
}

/** Format as "F. Lastname" */
function shortName(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return name
  return `${parts[0][0]}. ${parts.slice(1).join(' ')}`
}

const isKeyEvent = (ev: MatchEventData): boolean => {
  if (ev.event_type === 'Shot' && ev.details.shot_outcome === 'Goal') return true
  if (ev.details.foul_card && ev.details.foul_card !== '') return true
  if (ev.details.card && ev.details.card !== '') return true
  if (ev.event_type === 'Bad Behaviour') return true
  if (ev.event_type === 'Substitution') return true
  if (ev.event_type === 'Shot' && ev.details.shot_outcome !== 'Goal' && (ev.details.xg ?? 0) > 0.3) return true
  return false
}

function eventIcon(ev: MatchEventData): string {
  if (ev.event_type === 'Shot' && ev.details.shot_outcome === 'Goal') return '⚽'
  if (ev.details.foul_card === 'Yellow Card' || ev.details.card === 'Yellow Card') return '🟨'
  if (ev.details.foul_card === 'Red Card'    || ev.details.card === 'Red Card')    return '🟥'
  if (ev.event_type === 'Substitution') return '↕'
  if (ev.event_type === 'Shot') return '🎯'
  if (ev.event_type === 'Pass') return '→'
  if (ev.event_type === 'Dribble') return '✦'
  if (ev.event_type === 'Foul Committed') return '!'
  if (ev.event_type === 'Block') return '■'
  if (ev.event_type === 'Goal Keeper') return '🧤'
  return '·'
}

function formatDesc(ev: MatchEventData): string {
  if (ev.event_type === 'Shot') {
    const o = ev.details.shot_outcome
    if (o === 'Goal') return `GOAL! ${shortName(ev.player)}`
    return `${shortName(ev.player)} (${o ?? 'shot'})`
  }
  if (ev.event_type === 'Substitution' && ev.details.sub_replacement) {
    return `${shortName(ev.player)} ↔ ${shortName(ev.details.sub_replacement)}`
  }
  if ((ev.event_type === 'Foul Committed' || ev.event_type === 'Bad Behaviour') && (ev.details.foul_card || ev.details.card)) {
    return `${shortName(ev.player)} [${ev.details.foul_card ?? ev.details.card}]`
  }
  return shortName(ev.player) || ev.event_type
}

function formatDetail(ev: MatchEventData): string | null {
  const parts: string[] = []
  if (ev.event_type === 'Pass') {
    if (ev.details.cross) parts.push('cross')
    if (ev.details.pass_recipient) parts.push(`→ ${shortName(ev.details.pass_recipient)}`)
    if (ev.details.pass_outcome && ev.details.pass_outcome !== 'Complete')
      parts.push(`[${ev.details.pass_outcome}]`)
    if (ev.details.goal_assist) parts.push('🅰 assist')
  } else if (ev.event_type === 'Dribble') {
    if (ev.details.dribble_outcome) parts.push(ev.details.dribble_outcome)
  } else if (ev.event_type === 'Goal Keeper') {
    if (ev.details.gk_type)    parts.push(ev.details.gk_type)
    if (ev.details.gk_outcome) parts.push(ev.details.gk_outcome)
  } else if (ev.event_type === 'Shot') {
    if (ev.details.xg !== undefined && ev.details.xg > 0)
      parts.push(`xG ${ev.details.xg.toFixed(2)}`)
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

// ── Score Panel ────────────────────────────────────────────────────────────

function ScorePanel({
  homeTeam, awayTeam, homeColor, awayColor,
  score, matchTime, running, matchEnded, currentPeriod, goalEvents, matchMeta,
}: Pick<SidebarTabsProps,
  'homeTeam' | 'awayTeam' | 'homeColor' | 'awayColor' |
  'score' | 'matchTime' | 'running' | 'matchEnded' | 'currentPeriod' | 'goalEvents' | 'matchMeta'
>) {
  const homeGoals = goalEvents.filter(g => g.team === homeTeam)
  const awayGoals = goalEvents.filter(g => g.team === awayTeam)

  const statusLabel = matchEnded
    ? 'FT'
    : matchTime === 0
    ? 'Pre-match'
    : fmtClock(matchTime, currentPeriod)

  const metaParts: string[] = []
  if (matchMeta?.competition) metaParts.push(matchMeta.competition)
  if (matchMeta?.date)        metaParts.push(matchMeta.date)

  const venueParts: string[] = []
  if (matchMeta?.stadium) venueParts.push(matchMeta.stadium)
  if (matchMeta?.city)    venueParts.push(matchMeta.city)
  const venueStr = venueParts.join(', ')

  return (
    <div className="flex-shrink-0 border-b border-[#1e1e2e] px-3 pt-3 pb-2.5">
      {/* Competition / venue — compact single line */}
      {metaParts.length > 0 && (
        <p className="font-mono text-[9px] text-gray-600 tracking-wide text-center mb-2 truncate">
          {metaParts.join('  ·  ')}
          {venueStr && <span className="opacity-60">  ·  {venueStr}</span>}
        </p>
      )}

      {/* Score row */}
      <div className="flex items-center justify-between gap-2">
        {/* Home */}
        <div className="flex-1 min-w-0 flex flex-col items-end gap-0.5">
          <span
            className="font-sans font-bold text-sm leading-tight text-right truncate w-full"
            style={{ color: homeColor }}
          >
            {homeTeam}
          </span>
          <div className="flex flex-col items-end gap-px">
            {homeGoals.map((g, i) => (
              <span key={i} className="font-mono text-[9px] text-gray-500">
                {shortName(g.player)} {g.minute}'
                {g.is_own_goal && <span className="text-red-400 ml-0.5">og</span>}
              </span>
            ))}
          </div>
        </div>

        {/* Score + clock */}
        <div className="flex flex-col items-center flex-shrink-0 gap-1">
          <div className="flex items-center gap-1.5">
            <span className="font-mono font-black text-3xl text-white tabular-nums leading-none">
              {score.home}
            </span>
            <span className="font-mono text-gray-600 text-lg leading-none">–</span>
            <span className="font-mono font-black text-3xl text-white tabular-nums leading-none">
              {score.away}
            </span>
          </div>
          <div
            className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold
              ${matchEnded
                ? 'bg-gray-800 text-gray-400'
                : running
                ? 'bg-emerald-900/50 text-emerald-300 border border-emerald-700/40'
                : matchTime === 0
                ? 'bg-[#1a1a2c] text-gray-500 border border-[#252535]'
                : 'bg-[#1a1a2c] text-gray-300 border border-[#252535]'
              }`}
          >
            {running && <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />}
            {statusLabel}
          </div>
        </div>

        {/* Away */}
        <div className="flex-1 min-w-0 flex flex-col items-start gap-0.5">
          <span
            className="font-sans font-bold text-sm leading-tight truncate w-full"
            style={{ color: awayColor }}
          >
            {awayTeam}
          </span>
          <div className="flex flex-col items-start gap-px">
            {awayGoals.map((g, i) => (
              <span key={i} className="font-mono text-[9px] text-gray-500">
                {shortName(g.player)} {g.minute}'
                {g.is_own_goal && <span className="text-red-400 ml-0.5">og</span>}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Weather line */}
      {matchMeta?.weather && (
        <p className="font-mono text-[9px] text-gray-600 text-center mt-1.5 opacity-70">
          {matchMeta.weather}
        </p>
      )}
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function StatsTab({
  matchState, analysis, homeTeam, awayTeam, homeColor, awayColor,
}: Pick<SidebarTabsProps, 'matchState' | 'analysis' | 'homeTeam' | 'awayTeam' | 'homeColor' | 'awayColor'>) {
  if (!matchState) {
    return <EmptyMsg>Waiting for match data…</EmptyMsg>
  }

  const { stats, possession } = matchState
  const h = stats[homeTeam]
  const a = stats[awayTeam]

  if (!h || !a) return <EmptyMsg>No stats yet…</EmptyMsg>

  const homePos = possession[homeTeam] ?? 50
  const awayPos = possession[awayTeam] ?? 50

  const homeAcc = h.passes_attempted > 0 ? pct(h.passes_completed, h.passes_attempted) : 0
  const awayAcc = a.passes_attempted > 0 ? pct(a.passes_completed, a.passes_attempted) : 0

  const rows: { label: string; hv: number; av: number; fmt?: (v: number) => string; abs?: boolean }[] = [
    { label: 'Shots',        hv: h.shots,             av: a.shots },
    { label: 'On Target',    hv: h.shots_on_target,   av: a.shots_on_target },
    { label: 'xG',           hv: h.xg,                av: a.xg,    fmt: v => v.toFixed(2) },
    { label: 'Passes',       hv: h.passes_attempted,  av: a.passes_attempted },
    { label: 'Pass Acc.',    hv: homeAcc,             av: awayAcc, fmt: v => `${v}%`, abs: true },
    { label: 'Fouls',        hv: h.fouls,             av: a.fouls },
    { label: 'Yellow',       hv: h.yellow_cards,      av: a.yellow_cards },
    { label: 'Red',          hv: h.red_cards,         av: a.red_cards },
  ]

  const mom_h = analysis?.momentum_home ?? 50
  const mom_a = analysis?.momentum_away ?? 50

  return (
    <div className="flex flex-col gap-4 px-3 py-3 overflow-y-auto h-full">
      {analysis && (
        <div>
          <SectionLabel>Momentum</SectionLabel>
          <div className="flex h-2 rounded-full overflow-hidden mt-1.5 mb-1">
            <div className="transition-all duration-1000" style={{ width: `${mom_h}%`, backgroundColor: homeColor, opacity: 0.9 }} />
            <div className="transition-all duration-1000" style={{ width: `${mom_a}%`, backgroundColor: awayColor, opacity: 0.9 }} />
          </div>
          <div className="flex justify-between font-mono text-[10px]">
            <span style={{ color: homeColor }}>{mom_h.toFixed(0)}%</span>
            <span className="text-gray-600">
              xG {(analysis.xg_home).toFixed(2)} – {(analysis.xg_away).toFixed(2)}
            </span>
            <span style={{ color: awayColor }}>{mom_a.toFixed(0)}%</span>
          </div>
        </div>
      )}

      <div>
        <SectionLabel>Possession</SectionLabel>
        <div className="flex justify-between font-mono text-xs mt-1.5 mb-1">
          <span className="font-bold" style={{ color: homeColor }}>{homePos.toFixed(0)}%</span>
          <span className="font-bold" style={{ color: awayColor }}>{awayPos.toFixed(0)}%</span>
        </div>
        <div className="flex h-2 rounded-full overflow-hidden">
          <div className="transition-all duration-700" style={{ width: `${homePos}%`, backgroundColor: homeColor }} />
          <div className="transition-all duration-700" style={{ width: `${awayPos}%`, backgroundColor: awayColor }} />
        </div>
      </div>

      <div className="space-y-2.5">
        <SectionLabel>Match Stats</SectionLabel>
        {rows.map(row => {
          const total = row.hv + row.av
          const hp = row.abs ? row.hv : (total === 0 ? 50 : (row.hv / total) * 100)
          const ap = row.abs ? row.av : (total === 0 ? 50 : (row.av / total) * 100)
          const fmt = row.fmt ?? (v => String(v))
          return (
            <div key={row.label}>
              <div className="flex items-center justify-between text-[11px] mb-1">
                <span className="font-mono font-semibold text-gray-200 w-8 text-right">{fmt(row.hv)}</span>
                <span className="text-gray-500 text-[10px] uppercase tracking-wider flex-1 text-center">{row.label}</span>
                <span className="font-mono font-semibold text-gray-200 w-8 text-left">{fmt(row.av)}</span>
              </div>
              <div className="flex gap-0.5 h-1.5">
                <div className="flex-1 flex justify-end rounded-l overflow-hidden bg-[#1a1a28]">
                  <div className="h-full rounded-l transition-all duration-700" style={{ width: `${hp}%`, backgroundColor: homeColor, opacity: 0.8 }} />
                </div>
                <div className="flex-1 flex justify-start rounded-r overflow-hidden bg-[#1a1a28]">
                  <div className="h-full rounded-r transition-all duration-700" style={{ width: `${ap}%`, backgroundColor: awayColor, opacity: 0.8 }} />
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function LiveTab({
  recentEvents, homeTeam, awayTeam, homeColor, awayColor,
}: Pick<SidebarTabsProps, 'recentEvents' | 'homeTeam' | 'awayTeam' | 'homeColor' | 'awayColor'>) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const keyEvents = recentEvents.filter(isKeyEvent).slice(-60)
  const allEvents = recentEvents.slice(-100)
  const [showAll, setShowAll] = useState(false)
  const visible = showAll ? allEvents : keyEvents

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [visible.length])

  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b border-[#1a1a28] flex-shrink-0">
        {[false, true].map(all => (
          <button
            key={String(all)}
            onClick={() => setShowAll(all)}
            className={`flex-1 py-2 font-mono text-[10px] uppercase tracking-wider transition-colors
              ${showAll === all ? 'text-amber-400 border-b-2 border-amber-400' : 'text-gray-600 hover:text-gray-400'}`}
          >
            {all ? 'All Events' : 'Key Events'}
          </button>
        ))}
      </div>

      <div ref={containerRef} className="flex-1 overflow-y-auto py-1.5">
        {visible.length === 0 && <EmptyMsg>{showAll ? 'Waiting for events…' : 'No key events yet…'}</EmptyMsg>}
        {visible.map((ev, i) => {
          const isGoal = ev.event_type === 'Shot' && ev.details.shot_outcome === 'Goal'
          const isHome = ev.team === homeTeam
          const accentColor = isHome ? homeColor : awayColor
          return (
            <div
              key={ev.id || i}
              className={`flex items-start gap-2 px-3 py-1.5 text-xs border-l-2 transition-colors
                ${isGoal ? 'bg-red-900/15 border-red-500' : 'border-transparent hover:bg-[#111120]'}`}
              style={!isGoal ? { borderColor: 'transparent' } : undefined}
            >
              <span className="font-mono text-[10px] text-gray-600 flex-shrink-0 w-8 pt-px">{fmtMin(ev.timestamp_sec)}</span>
              <span className="flex-shrink-0 text-sm pt-px">{eventIcon(ev)}</span>
              <div className="flex-1 min-w-0">
                <p className={`truncate text-[11px] ${isGoal ? 'font-bold text-white' : 'text-gray-300'}`}>
                  {formatDesc(ev)}
                </p>
                {showAll && (
                  <p className="font-mono text-[9px] truncate" style={{ color: accentColor }}>
                    {ev.event_type} · {ev.team}
                  </p>
                )}
                {showAll && (() => { const d = formatDetail(ev); return d ? (
                  <p className="font-mono text-[9px] text-gray-600 truncate">{d}</p>
                ) : null })()}
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

function SquadTab({
  lineup, homeTeam, awayTeam, homeColor, awayColor,
}: Pick<SidebarTabsProps, 'lineup' | 'homeTeam' | 'awayTeam' | 'homeColor' | 'awayColor'>) {
  const home = lineup.filter(p => p.team === 'home')
  const away = lineup.filter(p => p.team === 'away')

  if (lineup.length === 0) return <EmptyMsg>Lineup not available</EmptyMsg>

  return (
    <div className="overflow-y-auto h-full px-3 py-2 space-y-4">
      {[
        { team: homeTeam, players: home, color: homeColor },
        { team: awayTeam, players: away, color: awayColor },
      ].map(({ team, players, color }) => (
        <div key={team}>
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider mb-2" style={{ color }}>
            {team}
          </p>
          <div className="space-y-1">
            {players.map((p, i) => (
              <div key={i} className="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-[#111120] transition-colors">
                <div
                  className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-[10px] font-mono font-bold text-white"
                  style={{ backgroundColor: color + '33', border: `1px solid ${color}55` }}
                >
                  {p.jersey_number}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-200 truncate">{shortName(p.name)}</p>
                  <p className="font-mono text-[9px] text-gray-600 truncate">{p.position}</p>
                </div>
                {p.goals > 0 && (
                  <span className="text-[10px] text-amber-400 font-mono">⚽{p.goals}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] text-gray-600 uppercase tracking-widest">{children}</p>
  )
}

function EmptyMsg({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center h-full px-4 py-8">
      <p className="font-mono text-xs text-gray-600 text-center">{children}</p>
    </div>
  )
}

// ── Main export ────────────────────────────────────────────────────────────

export const SidebarTabs: React.FC<SidebarTabsProps> = (props) => {
  const [tab, setTab] = useState<Tab>('stats')

  const TABS: { id: Tab; label: string }[] = [
    { id: 'stats', label: 'Stats' },
    { id: 'live',  label: 'Live' },
    { id: 'squad', label: 'Squad' },
  ]

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Compact score header */}
      <ScorePanel
        homeTeam={props.homeTeam}
        awayTeam={props.awayTeam}
        homeColor={props.homeColor}
        awayColor={props.awayColor}
        score={props.score}
        matchTime={props.matchTime}
        running={props.running}
        matchEnded={props.matchEnded}
        currentPeriod={props.currentPeriod}
        goalEvents={props.goalEvents}
        matchMeta={props.matchMeta}
      />

      {/* Tab header */}
      <div className="flex border-b border-[#1e1e2e] flex-shrink-0">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 py-2.5 font-mono text-[11px] uppercase tracking-wider transition-colors
              ${tab === t.id
                ? 'text-amber-400 border-b-2 border-amber-500'
                : 'text-gray-600 hover:text-gray-400'
              }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === 'stats' && <StatsTab {...props} />}
        {tab === 'live'  && <LiveTab  {...props} />}
        {tab === 'squad' && <SquadTab {...props} />}
      </div>
    </div>
  )
}
