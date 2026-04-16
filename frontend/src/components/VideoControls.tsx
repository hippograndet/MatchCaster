// frontend/src/components/VideoControls.tsx
// Video-player-style match controls: activity waveform seek bar, ±10/30s, speed, mute

import React, { useRef, useCallback, useMemo } from 'react'
import type { ActivityBucket, GoalMarker, PitchOverlays } from '../utils/types'

interface VideoControlsProps {
  running: boolean
  speed: number
  matchTime: number        // seconds elapsed
  totalTime: number        // estimated match duration in seconds
  currentPeriod: number    // 1 or 2 (for stoppage time display)
  matchEnded: boolean
  connected: boolean
  ttsReady: boolean
  muted: boolean
  homeColor: string
  awayColor: string
  activityBuckets: ActivityBucket[]
  goalMarkers: GoalMarker[]
  summaryLoading: boolean
  homeTeam: string
  overlays: PitchOverlays
  onToggleOverlay: (key: keyof PitchOverlays) => void
  onPlay: () => void
  onPause: () => void
  onSeek: (targetTime: number) => void
  onSpeedChange: (speed: number) => void
  onMuteToggle: () => void
  onOpenOverlay: () => void
  onChangeMatch: () => void
}

/** Format match clock with stoppage time: "45+2'" or "87'" */
function fmtMatchClock(sec: number, period: number): string {
  const min = Math.floor(Math.max(0, sec) / 60)
  const periodHalfEnd: Record<number, number> = { 1: 45, 2: 90, 3: 105, 4: 120 }
  const halfEnd = periodHalfEnd[period] ?? 90
  if (min <= halfEnd) return `${min}'`
  return `${halfEnd}+${min - halfEnd}'`
}

function fmtTime(sec: number): string {
  const m = Math.floor(Math.max(0, sec) / 60)
  const s = Math.floor(Math.max(0, sec) % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

const SPEEDS = [0.5, 1, 2, 4, 8]

const OVERLAY_BTNS: { key: keyof PitchOverlays; icon: string; title: string }[] = [
  { key: 'formation', icon: '👤', title: 'Lineup / Formation' },
  { key: 'heatmap',   icon: '🔥', title: 'Heatmap' },
  { key: 'shotmap',   icon: '🎯', title: 'Shot map' },
  { key: 'vectors',   icon: '↗',  title: 'Build-up vectors' },
]

export const VideoControls: React.FC<VideoControlsProps> = ({
  running, speed, matchTime, totalTime, currentPeriod, matchEnded,
  connected, ttsReady, muted,
  homeColor, awayColor, activityBuckets, goalMarkers, summaryLoading, homeTeam,
  overlays, onToggleOverlay,
  onPlay, onPause, onSeek, onSpeedChange, onMuteToggle,
  onOpenOverlay, onChangeMatch,
}) => {
  const barRef = useRef<HTMLDivElement>(null)
  const progress = totalTime > 0 ? Math.min(1, matchTime / totalTime) : 0
  const canControl = connected && !matchEnded

  const handleBarClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!barRef.current) return
    const rect = barRef.current.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    onSeek(Math.round(ratio * totalTime))
  }, [totalTime, onSeek])

  // Normalize activity buckets
  const { maxVal, normalizedBuckets } = useMemo(() => {
    if (activityBuckets.length === 0) return { maxVal: 1, normalizedBuckets: [] }
    const max = Math.max(1, ...activityBuckets.map(b => Math.max(b.home, b.away)))
    return { maxVal: max, normalizedBuckets: activityBuckets }
  }, [activityBuckets])

  const waveformHeight = 36  // px total (18 each side)

  // Shared seek bar JSX extracted so it can be placed in the left column
  const seekBar = (
    <div
      ref={barRef}
      onClick={handleBarClick}
      className={`relative w-full mb-2 rounded overflow-hidden
        ${canControl ? 'cursor-pointer' : 'cursor-default opacity-50'}`}
      style={{ height: waveformHeight }}
    >
      <div className="absolute inset-0 bg-[#111120] rounded" />

      {summaryLoading && (
        <div className="absolute inset-0 flex items-center justify-center gap-2">
          <div className="w-3 h-3 border border-gray-700 border-t-amber-500/60 rounded-full animate-spin" />
          <span className="font-mono text-[10px] text-gray-700">Compiling match data…</span>
        </div>
      )}

      {!summaryLoading && normalizedBuckets.length > 0 && totalTime > 0 && (
        <svg
          className="absolute inset-0 w-full h-full"
          preserveAspectRatio="none"
          viewBox={`0 0 ${normalizedBuckets.length} ${waveformHeight}`}
        >
          {normalizedBuckets.map((b, i) => {
            const homeH = (b.home / maxVal) * (waveformHeight / 2 - 2)
            const awayH = (b.away / maxVal) * (waveformHeight / 2 - 2)
            const mid = waveformHeight / 2
            return (
              <g key={i}>
                {homeH > 0 && <rect x={i} y={mid - homeH} width={0.8} height={homeH} fill={homeColor} opacity={0.6} />}
                {awayH > 0 && <rect x={i} y={mid} width={0.8} height={awayH} fill={awayColor} opacity={0.6} />}
              </g>
            )
          })}
        </svg>
      )}

      <div className="absolute left-0 right-0 bg-[#252535]" style={{ top: waveformHeight / 2, height: 1 }} />
      <div className="absolute top-0 bottom-0 left-0 bg-amber-500/10 pointer-events-none" style={{ width: `${progress * 100}%` }} />
      <div className="absolute top-0 bottom-0 w-0.5 bg-amber-400 pointer-events-none shadow-[0_0_6px_rgba(245,158,11,0.8)]" style={{ left: `${progress * 100}%` }} />

      {goalMarkers.map((g, i) => {
        const x = totalTime > 0 ? (g.timestamp_sec / totalTime) * 100 : 0
        const isHome = g.team === homeTeam
        const color = isHome ? homeColor : awayColor
        return (
          <div key={i} className="absolute top-0 bottom-0 flex flex-col items-center pointer-events-none" style={{ left: `${x}%` }}>
            <div className="absolute top-0 bottom-0 w-px opacity-80" style={{ backgroundColor: color }} />
            <div className="absolute text-[8px] leading-none -translate-x-1/2 font-bold" style={{ top: isHome ? 2 : undefined, bottom: isHome ? undefined : 2, color }}>⚽</div>
          </div>
        )
      })}

      {totalTime > 2700 && (
        <div className="absolute top-0 bottom-0 w-px bg-[#444460]/60 pointer-events-none" style={{ left: `${(2700 / totalTime) * 100}%` }} />
      )}
    </div>
  )

  return (
    <div className="flex-shrink-0 bg-[#0a0a12] border-t border-[#1e1e2e] select-none flex">

      {/* ── Left column: timeline + playback (aligns with pitch) ───────── */}
      <div className="flex-1 min-w-0 px-4 py-2">
        {seekBar}

        {/* Controls row */}
        <div className="flex items-center gap-2">

          {/* Skip back */}
          <div className="flex items-center gap-1">
            <SkipBtn label="−30s" disabled={!canControl} onClick={() => onSeek(Math.max(0, matchTime - 30))} title="Rewind 30 seconds" />
            <SkipBtn label="−10s" disabled={!canControl} onClick={() => onSeek(Math.max(0, matchTime - 10))} title="Rewind 10 seconds" />
          </div>

          {/* Play / Pause */}
          <div className="flex flex-col items-center gap-0.5">
            <button
              onClick={running ? onPause : onPlay}
              disabled={!connected || matchEnded || !ttsReady}
              title={!ttsReady ? 'Loading audio engine…' : running ? 'Pause' : 'Play'}
              className={`flex items-center justify-center w-9 h-9 rounded-full border transition-all
                disabled:opacity-40 disabled:cursor-not-allowed
                ${running
                  ? 'bg-amber-500 border-amber-400 text-black hover:bg-amber-400'
                  : 'bg-[#1a1a2c] border-[#2e2e45] text-gray-300 hover:border-amber-500/50 hover:text-white'
                }`}
            >
              {running ? (
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="6" y="4" width="4" height="16" rx="1" />
                  <rect x="14" y="4" width="4" height="16" rx="1" />
                </svg>
              ) : matchEnded ? (
                <span className="font-mono text-[9px] font-bold">FT</span>
              ) : (
                <svg className="w-4 h-4 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                  <polygon points="5,3 19,12 5,21" />
                </svg>
              )}
            </button>
            {connected && !ttsReady && !matchEnded && (
              <span className="font-mono text-[8px] text-gray-600 animate-pulse whitespace-nowrap">
                loading audio…
              </span>
            )}
          </div>

          {/* Skip forward */}
          <div className="flex items-center gap-1">
            <SkipBtn label="+10s" disabled={!canControl} onClick={() => onSeek(matchTime + 10)} title="Skip 10 seconds" />
            <SkipBtn label="+30s" disabled={!canControl} onClick={() => onSeek(matchTime + 30)} title="Skip 30 seconds" />
          </div>

          {/* Time display */}
          <div className="font-mono text-xs text-gray-400 tabular-nums ml-1 flex items-baseline gap-1.5 min-w-[110px]">
            <span className="text-gray-200 text-sm font-semibold">{fmtMatchClock(matchTime, currentPeriod)}</span>
            <span className="text-gray-700 text-[10px]">{fmtTime(matchTime)}</span>
            <span className="text-gray-700 text-[10px]">/ {fmtTime(totalTime)}</span>
          </div>

          <div className="flex-1" />

          {/* Speed */}
          <div className="flex items-center gap-0.5 rounded-lg border border-[#1e1e2e] overflow-hidden">
            {SPEEDS.map(v => (
              <button key={v} onClick={() => onSpeedChange(v)} disabled={!canControl}
                className={`px-2 py-1 font-mono text-[11px] transition-colors disabled:opacity-40
                  ${speed === v ? 'bg-amber-500/20 text-amber-400' : 'text-gray-500 hover:text-gray-300'}`}>
                {v}×
              </button>
            ))}
          </div>

          {/* Mute */}
          <button onClick={onMuteToggle} title={muted ? 'Unmute' : 'Mute'}
            className={`w-8 h-8 flex items-center justify-center rounded-lg border transition-all
              ${muted ? 'border-red-500/40 text-red-400 bg-red-900/15' : 'border-[#1e1e2e] text-gray-500 hover:text-gray-200 hover:border-[#2e2e45]'}`}>
            {muted ? (
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M16.5 12A4.5 4.5 0 0 0 14 8.1V10l2.45 2.45c.03-.15.05-.3.05-.45zM19 12c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.84 8.84 0 0 0 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06A8.99 8.99 0 0 0 17.73 19.73l1 1L20 19.46 4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 8.1v7.82c1.48-.73 2.5-2.25 2.5-4.42z"/>
              </svg>
            )}
          </button>

          {/* Connection dot */}
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />
            <span className="font-mono text-[10px] text-gray-600">{connected ? 'Live' : 'Off'}</span>
          </div>
        </div>
      </div>

      {/* ── Right column: overlay toggles (aligns with sidebar) ─────────── */}
      <div className="w-80 flex-shrink-0 border-l border-[#1e1e2e] px-3 py-2 flex flex-col justify-between">
        {/* Top row: overlay quick toggles + settings */}
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[9px] text-gray-600 uppercase tracking-widest mr-1">Overlays</span>
          <div className="flex items-center gap-0.5 rounded-lg border border-[#1e1e2e] overflow-hidden">
            {OVERLAY_BTNS.map(({ key, icon, title }) => (
              <button key={key} onClick={() => onToggleOverlay(key)} title={title}
                className={`w-8 h-8 flex items-center justify-center text-sm transition-colors
                  ${overlays[key] ? 'bg-amber-500/20 text-amber-300' : 'text-gray-600 hover:text-gray-300'}`}>
                {icon}
              </button>
            ))}
          </div>
          <button onClick={onOpenOverlay} title="More overlay settings"
            className="w-8 h-8 flex items-center justify-center rounded-lg border border-[#1e1e2e]
              text-gray-500 hover:text-gray-200 hover:border-[#2e2e45] transition-all">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 0 1 1.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.559.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.894.149c-.424.07-.764.383-.929.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 0 1-1.449.12l-.738-.527c-.35-.25-.806-.272-1.203-.107-.398.165-.71.505-.781.929l-.149.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 0 1-.12-1.45l.527-.737c.25-.35.272-.806.108-1.204-.165-.397-.506-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.108-1.204l-.526-.738a1.125 1.125 0 0 1 .12-1.45l.773-.773a1.125 1.125 0 0 1 1.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z" />
            </svg>
          </button>
        </div>
        {/* Bottom row: change match */}
        <div className="flex items-center gap-2 mt-1">
          <button onClick={onChangeMatch}
            className="px-3 py-1 rounded-lg border border-[#1e1e2e] font-mono text-[11px] text-gray-500
              hover:text-gray-200 hover:border-[#2e2e45] transition-all">
            Change Match
          </button>
        </div>
      </div>

    </div>
  )
}

function SkipBtn({
  label, disabled, onClick, title,
}: { label: string; disabled: boolean; onClick: () => void; title?: string }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="px-2 py-1 rounded font-mono text-[11px] text-gray-500 border border-[#1a1a28]
        hover:text-gray-200 hover:border-[#2e2e45] transition-all
        disabled:opacity-30 disabled:cursor-not-allowed"
    >
      {label}
    </button>
  )
}
