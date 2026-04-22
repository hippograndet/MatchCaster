// frontend/src/components/AgentPanel.tsx
// Shows which agent is speaking, last utterance text, with glow on active.

import React, { useEffect, useState } from 'react'
import type { AgentName } from '../../utils/types'
import type { AgentCommentary } from '../../hooks/useWebSocket'

interface AgentPanelProps {
  commentaries: Record<AgentName, AgentCommentary | null>
  activeAgent: AgentName | null
  isPlaying: boolean
}

interface AgentConfig {
  name: AgentName
  label: string
  description: string
  color: string
  glowClass: string
  borderColor: string
  bgActive: string
  icon: string
}

const AGENTS: AgentConfig[] = [
  {
    name: 'play_by_play',
    label: 'Play-by-Play',
    description: 'Live action narration',
    color: 'text-amber-400',
    glowClass: 'agent-active-pbp',
    borderColor: 'border-amber-500',
    bgActive: 'bg-amber-900/20',
    icon: '📢',
  },
  {
    name: 'tactical',
    label: 'Tactical',
    description: 'Formations & patterns',
    color: 'text-blue-400',
    glowClass: 'agent-active-tactical',
    borderColor: 'border-blue-500',
    bgActive: 'bg-blue-900/20',
    icon: '🧠',
  },
  {
    name: 'stats',
    label: 'Stats',
    description: 'Match statistics',
    color: 'text-emerald-400',
    glowClass: 'agent-active-stats',
    borderColor: 'border-emerald-500',
    bgActive: 'bg-emerald-900/20',
    icon: '📊',
  },
]

const ACTIVE_TIMEOUT_MS = 6000  // highlight fades after 6 seconds

export const AgentPanel: React.FC<AgentPanelProps> = ({
  commentaries,
  activeAgent,
  isPlaying,
}) => {
  const [recentActive, setRecentActive] = useState<Record<AgentName, number>>({
    play_by_play: 0,
    tactical: 0,
    stats: 0,
  })

  // Track when each agent last spoke
  useEffect(() => {
    for (const [name, commentary] of Object.entries(commentaries)) {
      if (commentary && commentary.timestamp > (recentActive[name as AgentName] ?? 0)) {
        setRecentActive(prev => ({ ...prev, [name]: commentary.timestamp }))
      }
    }
  }, [commentaries]) // eslint-disable-line react-hooks/exhaustive-deps

  const isAgentActive = (name: AgentName): boolean => {
    if (activeAgent === name && isPlaying) return true
    const lastActive = recentActive[name] ?? 0
    return Date.now() - lastActive < ACTIVE_TIMEOUT_MS
  }

  return (
    <div className="flex flex-col gap-3 h-full overflow-hidden">
      <h3 className="font-mono text-xs text-gray-500 uppercase tracking-widest px-1">
        Commentators
      </h3>
      <div className="flex flex-col gap-2 overflow-y-auto flex-1 pr-1">
        {AGENTS.map(agent => {
          const commentary = commentaries[agent.name]
          const active = isAgentActive(agent.name)
          const isSpeaking = activeAgent === agent.name && isPlaying

          return (
            <div
              key={agent.name}
              className={`
                rounded-lg border-l-4 p-3 transition-all duration-300
                ${active ? agent.borderColor : 'border-[#2d2d3d]'}
                ${active ? agent.bgActive : 'bg-[#13131a]'}
                ${isSpeaking ? agent.glowClass : ''}
              `}
            >
              {/* Header */}
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-sm">{agent.icon}</span>
                <span className={`font-mono text-xs font-medium uppercase tracking-wide ${active ? agent.color : 'text-gray-500'}`}>
                  {agent.label}
                </span>
                {isSpeaking && (
                  <span className="ml-auto flex gap-0.5">
                    {[0, 1, 2].map(i => (
                      <span
                        key={i}
                        className={`w-0.5 rounded-full ${agent.color.replace('text-', 'bg-')}`}
                        style={{
                          height: '12px',
                          animation: `bounce 0.8s ${i * 0.15}s ease-in-out infinite`,
                          display: 'block',
                        }}
                      />
                    ))}
                  </span>
                )}
              </div>
              {/* Text */}
              <p className={`font-sans text-sm leading-snug transition-opacity duration-500 ${active ? 'text-gray-200 opacity-100' : 'text-gray-600 opacity-60'}`}>
                {commentary?.text ?? (
                  <span className="italic text-gray-600">{agent.description}</span>
                )}
              </p>
              {/* Timestamp */}
              {commentary && (
                <div className="mt-1.5 font-mono text-xs text-gray-600">
                  {String(Math.floor(commentary.match_time / 60)).padStart(2, '0')}:{String(Math.floor(commentary.match_time % 60)).padStart(2, '0')}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
