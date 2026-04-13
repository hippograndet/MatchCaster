// frontend/src/components/CommentaryOverlay.tsx
// Glass-morphism commentary bar overlaid at the bottom of the pitch.

import React, { useState, useEffect } from 'react'
import type { AgentName } from '../utils/types'
import type { AgentCommentary } from '../hooks/useWebSocket'

interface CommentaryOverlayProps {
  latestCommentary: AgentCommentary | null
  activeAgent: AgentName | null
  isPlaying: boolean
}

const AGENT_ACCENT: Record<AgentName, string> = {
  play_by_play: '#f59e0b',   // amber
  tactical:     '#3b82f6',   // blue
  stats:        '#10b981',   // emerald
}

const AGENT_LABEL: Record<AgentName, string> = {
  play_by_play: '🎙',
  tactical:     '🧠',
  stats:        '📊',
}

const FADE_OUT_MS = 12000   // start fading after 12s
const HIDE_MS = 18000       // fully hidden after 18s

function formatTime(sec: number): string {
  return `${Math.floor(sec / 60)}'`
}

export const CommentaryOverlay: React.FC<CommentaryOverlayProps> = ({
  latestCommentary,
  activeAgent,
  isPlaying,
}) => {
  const [opacity, setOpacity] = useState(1)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!latestCommentary) return
    setOpacity(1)
    setVisible(true)

    const fadeTimer = setTimeout(() => {
      setOpacity(0)
    }, FADE_OUT_MS)

    const hideTimer = setTimeout(() => {
      setVisible(false)
    }, HIDE_MS)

    return () => {
      clearTimeout(fadeTimer)
      clearTimeout(hideTimer)
    }
  }, [latestCommentary])

  if (!visible || !latestCommentary) return null

  const agent = latestCommentary.agent
  const accent = AGENT_ACCENT[agent]
  const isSpeaking = activeAgent === agent && isPlaying

  return (
    <div
      className="absolute bottom-0 left-0 right-0 px-4 pb-3 pointer-events-none"
      style={{ transition: 'opacity 2s ease-out', opacity }}
    >
      <div
        className="rounded-xl px-4 py-3 flex items-start gap-3"
        style={{
          background: 'rgba(10, 10, 20, 0.82)',
          backdropFilter: 'blur(12px)',
          borderLeft: `3px solid ${accent}`,
          boxShadow: isSpeaking
            ? `0 0 20px ${accent}33, 0 4px 24px rgba(0,0,0,0.6)`
            : '0 4px 24px rgba(0,0,0,0.5)',
        }}
      >
        {/* Icon + speaking bars */}
        <div className="flex flex-col items-center gap-1 flex-shrink-0 pt-0.5">
          <span className="text-base">{AGENT_LABEL[agent]}</span>
          {isSpeaking && (
            <div className="flex gap-0.5">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="w-0.5 rounded-full"
                  style={{
                    height: 10,
                    backgroundColor: accent,
                    animation: `bounce 0.8s ${i * 0.15}s ease-in-out infinite`,
                    display: 'block',
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {/* Commentary text */}
        <div className="flex-1 min-w-0">
          <p className="font-sans text-sm text-gray-100 leading-snug">
            {latestCommentary.text}
          </p>
        </div>

        {/* Timestamp */}
        <span className="font-mono text-[11px] text-gray-500 flex-shrink-0 self-end">
          {formatTime(latestCommentary.match_time)}
        </span>
      </div>
    </div>
  )
}
