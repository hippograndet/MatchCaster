// frontend/src/components/EventLog.tsx
// Tabbed event log: Key Events | All Events

import React, { useEffect, useRef, useState } from 'react'
import type { MatchEventData } from '../utils/types'

interface EventLogProps {
  events: MatchEventData[]
}

type Tab = 'key' | 'all'

const isKeyEvent = (ev: MatchEventData): boolean => {
  // Goal
  if (ev.event_type === 'Shot' && ev.details.shot_outcome === 'Goal') return true
  // Yellow / red card
  if (ev.details.foul_card && ev.details.foul_card !== '') return true
  if (ev.details.card && ev.details.card !== '') return true
  if (ev.event_type === 'Bad Behaviour') return true
  // Substitution
  if (ev.event_type === 'Substitution') return true
  // Big chance missed: shot with xG > 0.3 that did NOT result in a goal
  if (
    ev.event_type === 'Shot' &&
    ev.details.shot_outcome !== 'Goal' &&
    (ev.details.xg ?? 0) > 0.3
  ) return true
  return false
}

const PRIORITY_STYLE: Record<string, string> = {
  critical: 'border-red-500 text-red-300',
  notable:  'border-amber-500/60 text-amber-300',
  routine:  'border-[#2a2a3d] text-gray-400',
}

const EVENT_ICONS: Record<string, string> = {
  Shot: '⚽',
  'Goal Keeper': '🧤',
  Pass: '→',
  Carry: '·',
  Dribble: '✦',
  Pressure: '↑',
  'Foul Committed': '!',
  'Bad Behaviour': '🟨',
  Substitution: '↔',
  Clearance: '↑',
  Interception: '✗',
  Block: '■',
  Offside: 'OFZ',
  'Ball Recovery': '◆',
}

function formatTime(sec: number): string {
  return `${Math.floor(sec / 60)}'`
}

function formatEvent(ev: MatchEventData): string {
  if (ev.event_type === 'Shot') {
    const outcome = ev.details.shot_outcome
    if (outcome === 'Goal') return `${ev.player} — GOAL! ⚽`
    if (outcome) return `${ev.player} (${outcome})`
    return ev.player
  }
  if (ev.event_type === 'Pass' && ev.details.pass_recipient) {
    let desc = `${ev.player} → ${ev.details.pass_recipient}`
    if (ev.details.goal_assist) desc += ' 🅰'
    return desc
  }
  if (ev.event_type === 'Substitution' && ev.details.sub_replacement) {
    return `${ev.player} ↔ ${ev.details.sub_replacement}`
  }
  if (ev.event_type === 'Foul Committed' && ev.details.foul_card) {
    return `${ev.player} [${ev.details.foul_card}]`
  }
  if (ev.event_type === 'Bad Behaviour' && ev.details.card) {
    return `${ev.player} [${ev.details.card}]`
  }
  return ev.player || ev.event_type
}

export const EventLog: React.FC<EventLogProps> = ({ events }) => {
  const [tab, setTab] = useState<Tab>('key')
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const visible = tab === 'key'
    ? events.filter(isKeyEvent).slice(-60)
    : events.slice(-80)

  // Auto-scroll on new events
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100
    if (nearBottom) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [visible.length])

  return (
    <div className="flex flex-col h-full">
      {/* Tabs */}
      <div className="flex border-b border-[#1e1e30] flex-shrink-0">
        {(['key', 'all'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-1.5 font-mono text-[10px] uppercase tracking-widest transition-colors ${
              tab === t
                ? 'text-amber-400 border-b-2 border-amber-400'
                : 'text-gray-600 hover:text-gray-400'
            }`}
          >
            {t === 'key' ? 'Key Events' : 'All Events'}
          </button>
        ))}
      </div>

      {/* Events list */}
      <div ref={containerRef} className="flex-1 overflow-y-auto space-y-0.5 pt-1 pr-0.5">
        {visible.length === 0 && (
          <p className="font-mono text-xs text-gray-600 italic px-2 pt-3 text-center">
            {tab === 'key' ? 'No key events yet…' : 'Waiting for events…'}
          </p>
        )}
        {visible.map((ev, idx) => {
          const isGoal = ev.event_type === 'Shot' && ev.details.shot_outcome === 'Goal'
          const pStyle = PRIORITY_STYLE[ev.priority] ?? PRIORITY_STYLE.routine
          const icon = EVENT_ICONS[ev.event_type] ?? '·'

          return (
            <div
              key={ev.id || idx}
              className={`flex items-start gap-1.5 px-2 py-1 rounded border-l-2 text-xs ${pStyle} ${
                isGoal ? 'bg-red-900/20' : ''
              }`}
            >
              <span className="font-mono text-gray-600 flex-shrink-0 w-9 text-right">
                {formatTime(ev.timestamp_sec)}
              </span>
              <span className="flex-shrink-0 w-4 text-center opacity-70">{icon}</span>
              <div className="flex-1 min-w-0">
                <span className={isGoal ? 'font-bold' : ''}>{formatEvent(ev)}</span>
                {tab === 'all' && (
                  <span className="text-gray-600 ml-1 text-[10px]">({ev.team})</span>
                )}
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
