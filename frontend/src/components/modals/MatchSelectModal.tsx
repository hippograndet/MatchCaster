// frontend/src/components/MatchSelectModal.tsx
// Full-screen launch screen: match selection + commentary style

import React, { useEffect, useState } from 'react'
import type { MatchInfo, Personality } from '../../utils/types'

interface MatchSelectModalProps {
  onStart: (matchId: string, personality: Personality) => void
}

const PERSONALITIES: { value: Personality; icon: string; label: string; desc: string }[] = [
  { value: 'neutral',      icon: '🎙', label: 'Neutral',      desc: 'Balanced & professional' },
  { value: 'enthusiastic', icon: '🔥', label: 'Enthusiastic', desc: 'High energy & emotional' },
  { value: 'analytical',   icon: '📐', label: 'Analytical',   desc: 'Tactical & data-driven' },
  { value: 'home_bias',    icon: '🏠', label: 'Home Fan',     desc: 'Rooting for home side' },
  { value: 'away_bias',    icon: '✈️', label: 'Away Fan',     desc: 'Rooting for away side' },
]

export const MatchSelectModal: React.FC<MatchSelectModalProps> = ({ onStart }) => {
  const [matches, setMatches] = useState<MatchInfo[]>([])
  const [selected, setSelected] = useState('')
  const [personality, setPersonality] = useState<Personality>('neutral')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch('/api/matches')
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then((data: MatchInfo[]) => { setMatches(data); setLoading(false) })
      .catch(() => { setError(true); setLoading(false) })
  }, [])

  const formatLabel = (m: MatchInfo) =>
    m.teams.length >= 2 ? `${m.teams[0]} vs ${m.teams[1]}` : `Match ${m.match_id}`

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#06060f] p-6 overflow-y-auto">
      {/* Brand */}
      <div className="mb-10 text-center select-none">
        <div className="font-mono text-5xl font-extrabold tracking-widest">
          <span className="text-amber-400">MATCH</span>
          <span className="text-white">CASTER</span>
        </div>
        <div className="mt-2 font-mono text-[11px] text-gray-600 tracking-[0.3em] uppercase">
          AI Football Commentary Engine
        </div>
      </div>

      <div className="w-full max-w-xl space-y-8">
        {/* Match selector */}
        <section>
          <h2 className="font-mono text-[10px] text-gray-500 uppercase tracking-[0.2em] mb-3">
            Select Match
          </h2>
          {loading ? (
            <div className="flex items-center gap-2 text-gray-600 text-sm font-mono py-4">
              <span className="inline-block w-3 h-3 border border-gray-600 border-t-amber-400 rounded-full animate-spin" />
              Loading matches...
            </div>
          ) : error ? (
            <div className="rounded-xl border border-red-900/50 bg-red-950/30 px-4 py-4 space-y-2">
              <p className="font-mono text-sm text-red-400 font-semibold">⚠ Cannot reach backend</p>
              <p className="font-mono text-xs text-gray-500 leading-relaxed">
                The backend isn't running. Start it with:
              </p>
              <pre className="font-mono text-xs text-amber-400 bg-[#0a0a12] rounded-lg px-3 py-2 select-all">
                ./start.sh
              </pre>
              <p className="font-mono text-xs text-gray-600">
                Then refresh this page.
              </p>
            </div>
          ) : matches.length === 0 ? (
            <div className="rounded-xl border border-yellow-900/40 bg-yellow-950/20 px-4 py-4 space-y-2">
              <p className="font-mono text-sm text-yellow-400 font-semibold">⚠ No matches found</p>
              <p className="font-mono text-xs text-gray-500 leading-relaxed">
                Run the data setup script first:
              </p>
              <pre className="font-mono text-xs text-amber-400 bg-[#0a0a12] rounded-lg px-3 py-2 select-all">
                cd data && bash setup.sh
              </pre>
            </div>
          ) : (
            <div className="space-y-2">
              {matches.map(m => (
                <button
                  key={m.match_id}
                  onClick={() => setSelected(m.match_id)}
                  className={`w-full flex items-center justify-between px-4 py-3 rounded-xl border text-left
                    transition-all duration-150 group
                    ${selected === m.match_id
                      ? 'border-amber-500/70 bg-amber-500/8 shadow-[0_0_16px_rgba(245,158,11,0.1)]'
                      : 'border-[#1e1e30] bg-[#0d0d18] hover:border-[#2e2e45] hover:bg-[#111120]'
                    }`}
                >
                  <div className="flex items-center gap-3">
                    <span className={`text-lg ${selected === m.match_id ? 'opacity-100' : 'opacity-60 group-hover:opacity-80'}`}>
                      ⚽
                    </span>
                    <div>
                      <div className={`font-sans text-sm font-semibold ${selected === m.match_id ? 'text-white' : 'text-gray-300'}`}>
                        {formatLabel(m)}
                      </div>
                      <div className="font-mono text-[10px] text-gray-600 mt-0.5">
                        {m.event_count.toLocaleString()} events
                      </div>
                    </div>
                  </div>
                  {selected === m.match_id && (
                    <span className="text-amber-400 text-sm">✓</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Personality selector */}
        <section>
          <h2 className="font-mono text-[10px] text-gray-500 uppercase tracking-[0.2em] mb-3">
            Commentary Style
          </h2>
          <div className="grid grid-cols-5 gap-2">
            {PERSONALITIES.map(p => (
              <button
                key={p.value}
                onClick={() => setPersonality(p.value)}
                title={p.desc}
                className={`flex flex-col items-center gap-2 py-3 px-1 rounded-xl border transition-all duration-150
                  ${personality === p.value
                    ? 'border-amber-500/60 bg-amber-500/8 text-white'
                    : 'border-[#1e1e30] bg-[#0d0d18] text-gray-500 hover:border-[#2e2e45] hover:text-gray-300'
                  }`}
              >
                <span className="text-xl leading-none">{p.icon}</span>
                <span className="font-mono text-[9px] uppercase tracking-wide leading-tight text-center">
                  {p.label}
                </span>
              </button>
            ))}
          </div>
        </section>

        {/* CTA */}
        <button
          onClick={() => selected && onStart(selected, personality)}
          disabled={!selected}
          className="w-full py-4 rounded-xl font-mono font-bold text-sm tracking-[0.15em] uppercase
            bg-amber-500 text-black hover:bg-amber-400 active:bg-amber-600
            transition-all duration-150 shadow-[0_0_24px_rgba(245,158,11,0.3)]
            disabled:opacity-25 disabled:cursor-not-allowed disabled:shadow-none"
        >
          Watch Live →
        </button>
      </div>

      {/* Footer note */}
      <p className="mt-8 font-mono text-[10px] text-gray-700">
        All data processed locally · No external tracking
      </p>
    </div>
  )
}
