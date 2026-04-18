// frontend/src/App.tsx

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { PitchCanvas } from './components/PitchCanvas'
import type { PossessionSegment, DangerEntry } from './components/PitchCanvas'
import { SidebarTabs } from './components/SidebarTabs'
import { VideoControls } from './components/VideoControls'
import { OverlayPanel } from './components/OverlayPanel'
import { MatchSelectModal } from './components/MatchSelectModal'
import { CommentaryOverlay } from './components/CommentaryOverlay'
import DevPanel from './components/DevPanel'
import { useWebSocket } from './hooks/useWebSocket'
import type { AgentCommentary, BackendInfo } from './hooks/useWebSocket'
import { useAudioPlayer } from './hooks/useAudioPlayer'
import type {
  PitchMarker, PitchOverlays, Personality, HeatmapTeam, LineupPlayer, MatchInfo,
  ActivityBucket, GoalMarker, GoalEvent,
} from './utils/types'

const IS_DEV = new URLSearchParams(window.location.search).has('dev')

const MARKER_MAX_AGE_MS = 10_000

const POSSESSION_IGNORE = new Set([
  'Pressure', 'Block', 'Duel', 'Foul Won', '50/50',
  'Camera On', 'Camera off', 'Offside',
])

function getSegmentType(
  eventType: string,
  details: { cross?: boolean } | undefined
): PossessionSegment['type'] | null {
  if (eventType === 'Carry')   return 'carry'
  if (eventType === 'Dribble') return 'dribble'
  if (eventType === 'Shot')    return 'shot'
  if (eventType === 'Pass')    return details?.cross ? 'cross' : 'pass'
  return null
}

function endsPossession(eventType: string, details: {
  pass_outcome?: string
  dribble_outcome?: string
} | undefined): boolean {
  if (eventType === 'Shot')           return true
  if (eventType === 'Clearance')      return true
  if (eventType === 'Foul Committed') return true
  if (eventType === 'Miscontrol')     return true
  if (eventType === 'Error')          return true
  if (eventType === 'Interception')   return true
  if (eventType === 'Dribble' && details?.dribble_outcome === 'Incomplete') return true
  if (eventType === 'Pass') {
    const o = details?.pass_outcome
    if (o && o !== 'Complete') return true
  }
  return false
}

const SKIP_TYPES = new Set([
  'Ball Receipt*', 'Ball Recovery', 'Starting XI',
  'Half Start', 'Half End', 'Referee Ball-Drop',
])

const HEATMAP_COLS = 24
const HEATMAP_ROWS = 16

const POSITION_MAP: Record<string, [number, number]> = {
  'Goalkeeper':               [4,  40],
  'Center Back':              [18, 40],
  'Left Center Back':         [18, 52],
  'Right Center Back':        [18, 28],
  'Left Back':                [16, 68],
  'Right Back':               [16, 12],
  'Left Wing Back':           [26, 72],
  'Right Wing Back':          [26,  8],
  'Defensive Midfield':       [30, 40],
  'Left Defensive Midfield':  [30, 54],
  'Right Defensive Midfield': [30, 26],
  'Center Midfield':          [38, 40],
  'Left Center Midfield':     [38, 54],
  'Right Center Midfield':    [38, 26],
  'Left Midfield':            [36, 68],
  'Right Midfield':           [36, 12],
  'Attacking Midfield':       [46, 40],
  'Left Attacking Midfield':  [44, 60],
  'Right Attacking Midfield': [44, 20],
  'Center Forward':           [55, 40],
  'Left Center Forward':      [53, 54],
  'Right Center Forward':     [53, 26],
  'Left Wing':                [51, 72],
  'Right Wing':               [51,  8],
  'Secondary Striker':        [51, 40],
}

const emptyGrid = () =>
  Array.from({ length: HEATMAP_ROWS }, () => new Array(HEATMAP_COLS).fill(0))

// ── Color utilities ───────────────────────────────────────────────────────

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '').padEnd(6, '0')
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
}

function colorsSimilar(c1: string, c2: string, threshold = 80): boolean {
  try {
    const [r1, g1, b1] = hexToRgb(c1)
    const [r2, g2, b2] = hexToRgb(c2)
    return Math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) < threshold
  } catch { return false }
}

// ── Goal flash overlay ────────────────────────────────────────────────────

interface GoalFlash { color: string; scorer: string; team: string; key: number }

function GoalFlashOverlay({ flash }: { flash: GoalFlash }) {
  const rings = [0, 0.35, 0.7]
  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden" style={{ zIndex: 40 }}>
      {/* Color wash */}
      <div
        className="goal-anim-bg absolute inset-0"
        style={{
          background: `radial-gradient(ellipse at center, ${flash.color}cc 0%, ${flash.color}55 60%, transparent 100%)`,
        }}
      />
      {/* Expanding rings */}
      {rings.map((delay, i) => (
        <div key={i} className="absolute inset-0 flex items-center justify-center">
          <div
            className="goal-anim-ring"
            style={{ animationDelay: `${delay}s`, borderColor: flash.color }}
          />
        </div>
      ))}
      {/* Text block */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 select-none">
        <div
          className="goal-anim-title font-black tracking-tight"
          style={{
            fontSize: 'clamp(52px, 9vw, 100px)',
            color: '#ffffff',
            textShadow: `0 0 40px ${flash.color}, 0 0 80px ${flash.color}88, 0 4px 20px rgba(0,0,0,0.8)`,
            lineHeight: 1,
          }}
        >
          ⚽ GOAL!
        </div>
        <div
          className="goal-anim-sub font-bold"
          style={{
            fontSize: 'clamp(14px, 2.5vw, 26px)',
            color: '#ffffff',
            textShadow: '0 2px 12px rgba(0,0,0,0.9)',
          }}
        >
          {flash.scorer}
        </div>
        <div
          className="goal-anim-sub2 font-mono uppercase tracking-widest"
          style={{
            fontSize: 'clamp(9px, 1.4vw, 14px)',
            color: flash.color,
            textShadow: `0 0 12px ${flash.color}`,
          }}
        >
          {flash.team}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  // ── UI state ──────────────────────────────────────────────────────────
  const [showModal,   setShowModal]   = useState(true)
  const [showOverlay, setShowOverlay] = useState(false)
  const [darkMode,    setDarkMode]    = useState(true)

  // ── Match selection ───────────────────────────────────────────────────
  const [selectedMatch, setSelectedMatch] = useState<string | null>(null)
  const [totalTime,     setTotalTime]     = useState(5400)

  // ── Pitch state ───────────────────────────────────────────────────────
  const [overlays, setOverlays] = useState<PitchOverlays>({
    live: true, formation: false, heatmap: false, shotmap: false, vectors: false,
  })
  const [heatmapTeam,       setHeatmapTeam]       = useState<HeatmapTeam>('home')
  const [heatmapGranularity,setHeatmapGranularity]= useState(4)
  const [personality,       setPersonality]       = useState<Personality>('neutral')
  const [markers,           setMarkers]           = useState<PitchMarker[]>([])
  const [activePossession,  setActivePossession]  = useState<PossessionSegment[] | null>(null)
  const [lastPossession,    setLastPossession]    = useState<PossessionSegment[] | null>(null)
  const [dangerEntries,     setDangerEntries]     = useState<DangerEntry[]>([])

  const possessionSegmentsRef  = useRef<PossessionSegment[]>([])
  const possessionTeamRef      = useRef<string | null>(null)
  const possessionIdRef        = useRef<number>(0)
  const [lineup,            setLineup]            = useState<LineupPlayer[]>([])
  const [heatmapHome,       setHeatmapHome]       = useState<number[][]>(emptyGrid)
  const [heatmapAway,       setHeatmapAway]       = useState<number[][]>(emptyGrid)
  const [activityBuckets,   setActivityBuckets]   = useState<ActivityBucket[]>([])
  const [goalMarkers,       setGoalMarkers]       = useState<GoalMarker[]>([])
  const [summaryLoading,    setSummaryLoading]    = useState(false)

  // ── Goal flash ────────────────────────────────────────────────────────
  const [goalFlash,      setGoalFlash]      = useState<GoalFlash | null>(null)
  const prevGoalCountRef = useRef(0)
  const goalFlashKeyRef  = useRef(0)

  // ── WebSocket ─────────────────────────────────────────────────────────
  const {
    connected, matchState, matchTime, displayTime, speed, running, matchEnded, currentPeriod,
    recentEvents, goalEvents, matchMeta, analysis,
    ttsReady, backendInfo,
    setOnAudioReceived, sendAction, debugTraces,
  } = useWebSocket(selectedMatch)

  // ── Audio ─────────────────────────────────────────────────────────────
  const { activeAgent, isPlaying, handleAudioMessage, setMuted, muted, setOnPlaybackStarted } = useAudioPlayer()
  const [latestCommentary, setLatestCommentary] = useState<AgentCommentary | null>(null)

  useEffect(() => { setOnAudioReceived(handleAudioMessage) }, [setOnAudioReceived, handleAudioMessage])
  useEffect(() => {
    setOnPlaybackStarted(e => setLatestCommentary({ ...e, timestamp: Date.now() }))
    return () => setOnPlaybackStarted(null)
  }, [setOnPlaybackStarted])

  // ── Derived colors (with clash detection) ────────────────────────────
  const homeColorPrimary   = matchMeta?.home_colors?.primary   ?? '#22c55e'
  const homeColorSecondary = matchMeta?.home_colors?.secondary ?? '#16a34a'
  const awayColorPrimary   = matchMeta?.away_colors?.primary   ?? '#3b82f6'
  const awayColorSecondary = matchMeta?.away_colors?.secondary ?? '#1d4ed8'

  // If primary colors are too similar, the away team shows their secondary color instead
  const effectiveAwayColor = colorsSimilar(homeColorPrimary, awayColorPrimary)
    ? awayColorSecondary
    : awayColorPrimary

  const homeColor = homeColorPrimary
  const awayColor = effectiveAwayColor
  const homeTeam  = matchState?.home_team ?? 'Home'
  const awayTeam  = matchState?.away_team ?? 'Away'
  const score     = matchState?.score ?? { home: 0, away: 0 }

  // ── Detect new goals → trigger flash ─────────────────────────────────
  useEffect(() => {
    if (goalEvents.length > prevGoalCountRef.current) {
      const latest = goalEvents[goalEvents.length - 1] as GoalEvent
      const teamColor = latest.team === homeTeam ? homeColor : awayColor
      goalFlashKeyRef.current += 1
      setGoalFlash({ color: teamColor, scorer: latest.player, team: latest.team, key: goalFlashKeyRef.current })
    }
    prevGoalCountRef.current = goalEvents.length
  }, [goalEvents.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-clear goal flash after animation
  useEffect(() => {
    if (!goalFlash) return
    const t = setTimeout(() => setGoalFlash(null), 3600)
    return () => clearTimeout(t)
  }, [goalFlash])

  // ── Event → pitch markers + heatmap ──────────────────────────────────
  useEffect(() => {
    if (recentEvents.length === 0) return
    const latest = recentEvents[recentEvents.length - 1]
    if (!latest || SKIP_TYPES.has(latest.event_type)) return
    const now = Date.now()

    const marker: PitchMarker = {
      id: latest.id,
      position: latest.position,
      end_position: latest.end_position,
      event_type: latest.event_type,
      team: latest.team,
      priority: latest.priority,
      age: 0,
      timestamp: now,
      details: latest.details as Record<string, unknown>,
    }
    setMarkers(prev => {
      const filtered = prev.filter(m => now - m.timestamp < MARKER_MAX_AGE_MS)
      if (filtered.some(m => m.id === marker.id)) return filtered
      return [...filtered, marker]
    })

    if (!POSSESSION_IGNORE.has(latest.event_type)) {
      const segType = getSegmentType(latest.event_type, latest.details)
      const teamChanged = possessionTeamRef.current !== null && latest.team !== possessionTeamRef.current

      if (teamChanged) {
        if (possessionSegmentsRef.current.length > 0) {
          setLastPossession([...possessionSegmentsRef.current])
        }
        setActivePossession(null)
        possessionSegmentsRef.current = []
        possessionTeamRef.current = null
      }

      if (segType && latest.end_position) {
        const segs = possessionSegmentsRef.current
        if (segs.length > 0) {
          const prev = segs[segs.length - 1]
          prev.durationMs = Math.max(150, now - prev.arrivalWallMs)
        }

        if (!possessionTeamRef.current) {
          possessionIdRef.current += 1
          possessionTeamRef.current = latest.team
        }

        const [fx, fy] = latest.position
        const [tx, ty] = latest.end_position
        const dist = Math.sqrt((tx - fx) ** 2 + (ty - fy) ** 2)
        const rawDurationSec = typeof (latest.details as Record<string, unknown>)?.duration === 'number'
          ? (latest.details as Record<string, unknown>).duration as number
          : null
        // Real-time ms: convert game-seconds to wall-ms, scaled by playback speed.
        // 0 signals PitchCanvas to fall back to distance-based speed constants.
        const durationMs = rawDurationSec != null
          ? Math.max(60, (rawDurationSec * 1000) / Math.max(0.25, speed))
          : 0

        const seg: PossessionSegment = {
          from: latest.position,
          to:   latest.end_position,
          team: latest.team,
          player: latest.player,
          type: segType,
          gameTimeSec:   latest.timestamp_sec,
          arrivalWallMs: now,
          durationMs,
          possessionId:  possessionIdRef.current,
          segmentIndex:  possessionSegmentsRef.current.length,
        }

        possessionSegmentsRef.current = [...possessionSegmentsRef.current, seg]
        setActivePossession([...possessionSegmentsRef.current])
      }

      if (
        possessionTeamRef.current &&
        latest.team === possessionTeamRef.current &&
        endsPossession(latest.event_type, latest.details)
      ) {
        setLastPossession([...possessionSegmentsRef.current])
        setActivePossession(null)
        possessionSegmentsRef.current = []
        possessionTeamRef.current = null
      }
    }

    if ((latest.event_type === 'Pass' || latest.event_type === 'Carry') && latest.end_position) {
      const [ex, ey] = latest.end_position
      const inY = ey >= 18 && ey <= 62
      const isHome = matchState && latest.team === matchState.home_team
      const isDangerous = inY && (isHome ? ex > 102 : ex < 18)
      if (isDangerous) {
        const entry: DangerEntry = { position: latest.end_position, team: latest.team, timestamp: now }
        setDangerEntries(prev => [...prev.filter(e => now - e.timestamp < 4000), entry])
      }
    }

    const [x, y] = latest.position
    const col = Math.min(HEATMAP_COLS - 1, Math.floor((x / 120) * HEATMAP_COLS))
    const row = Math.min(HEATMAP_ROWS - 1, Math.floor(((80 - y) / 80) * HEATMAP_ROWS))
    const isHome = matchState && latest.team === matchState.home_team
    const setter = isHome ? setHeatmapHome : setHeatmapAway
    setter(prev => {
      const next = prev.map(r => [...r])
      next[row][col] += 1
      return next
    })
  }, [recentEvents]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Load lineup ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!selectedMatch || !matchState) return
    fetch(`/api/lineup/${selectedMatch}`)
      .then(r => r.json())
      .then((data: { home: Array<{ name: string; jersey_number: number; positions: string[] }>;
                     away: Array<{ name: string; jersey_number: number; positions: string[] }> }) => {
        const players: LineupPlayer[] = []
        const processTeam = (
          teamPlayers: typeof data.home,
          team: 'home' | 'away',
          color: string,
        ) => {
          teamPlayers.forEach(p => {
            const pos = p.positions?.[0] ?? 'Center Midfield'
            const base = POSITION_MAP[pos] ?? [38, 40]
            const coords: [number, number] = team === 'away'
              ? [120 - base[0], 80 - base[1]]
              : base
            players.push({
              name: p.name, jersey_number: p.jersey_number,
              position: pos, x: coords[0], y: coords[1],
              goals: 0, assists: 0, team, teamColor: color,
            })
          })
        }
        processTeam(data.home, 'home', homeColor)
        processTeam(data.away, 'away', awayColor)
        goalEvents.forEach(g => {
          const pl = players.find(p => p.name === g.player || p.name.endsWith(g.player))
          if (pl) pl.goals += 1
        })
        setLineup(players)
      })
      .catch(() => {})
  }, [selectedMatch, matchState?.home_team]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Update lineup goals ───────────────────────────────────────────────
  useEffect(() => {
    if (goalEvents.length === 0) return
    setLineup(prev => {
      const updated = prev.map(p => ({ ...p, goals: 0, assists: 0 }))
      goalEvents.forEach(g => {
        const pl = updated.find(p =>
          p.name === g.player || p.name.split(' ').pop() === g.player || p.name.includes(g.player)
        )
        if (pl) pl.goals += 1
      })
      return updated
    })
  }, [goalEvents])

  // ── Handlers ──────────────────────────────────────────────────────────
  const handlePlay        = useCallback(() => sendAction('play', { speed }), [sendAction, speed])
  const handlePause       = useCallback(() => sendAction('pause'), [sendAction])
  const handleSeek        = useCallback((t: number) => {
    sendAction('seek', { target_time: t })
    setActivePossession(null)
    setLastPossession(null)
    possessionSegmentsRef.current = []
    possessionTeamRef.current = null
    possessionIdRef.current += 1
    setMarkers([])
    setDangerEntries([])
    setLatestCommentary(null)
  }, [sendAction])
  const handleSpeedChange = useCallback((s: number) => sendAction('set_speed', { speed: s }), [sendAction])
  const handlePersonalityChange = useCallback((p: Personality) => {
    setPersonality(p)
    sendAction('set_personality', { personality: p })
  }, [sendAction])

  const toggleOverlay = useCallback((key: keyof PitchOverlays) => {
    setOverlays(prev => ({ ...prev, [key]: !prev[key] }))
  }, [])

  const handleStart = useCallback((matchId: string, pers: Personality) => {
    setShowModal(false)
    setMarkers([]); setActivePossession(null); setLastPossession([]); setDangerEntries([]); setLineup([])
    possessionSegmentsRef.current = []; possessionTeamRef.current = null; possessionIdRef.current = 0
    setHeatmapHome(emptyGrid()); setHeatmapAway(emptyGrid())
    setActivityBuckets([]); setGoalMarkers([])
    setOverlays({ live: true, formation: false, heatmap: false, shotmap: false, vectors: false })
    setPersonality(pers)
    setSelectedMatch(matchId)
    prevGoalCountRef.current = 0
    fetch('/api/matches')
      .then(r => r.json())
      .then((ms: MatchInfo[]) => {
        const m = ms.find(x => x.match_id === matchId)
        if (m) setTotalTime(m.total_time ?? 5400)
      })
      .catch(() => {})
    setSummaryLoading(true)
    fetch(`/api/match_summary/${matchId}`)
      .then(r => r.json())
      .then(data => {
        setActivityBuckets(data.buckets ?? [])
        setGoalMarkers(data.goals ?? [])
      })
      .catch(() => {})
      .finally(() => setSummaryLoading(false))
  }, [])

  return (
    <div
      className="flex flex-col h-screen text-gray-100 overflow-hidden"
      style={{ background: 'var(--bg-deep)' }}
      data-theme={darkMode ? 'dark' : 'light'}
    >

      {showModal && <MatchSelectModal onStart={handleStart} />}

      {/* ── Top bar ──────────────────────────────────────────────── */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b border-[#1e1e2e] flex-shrink-0"
        style={{ background: 'var(--bg-panel)' }}
      >
        <button
          onClick={() => setShowModal(true)}
          className="font-mono font-extrabold text-sm tracking-widest hover:opacity-80 transition-opacity"
        >
          <span className="text-amber-400">MATCH</span>
          <span className="text-white">CASTER</span>
        </button>
        <div className="flex items-center gap-3">
          {selectedMatch && (
            <button
              onClick={() => setShowModal(true)}
              className="font-mono text-[11px] text-gray-500 hover:text-gray-300 transition-colors
                px-3 py-1 rounded-lg border border-[#1e1e2e] hover:border-[#2e2e45]"
            >
              Change Match
            </button>
          )}
          {backendInfo && (
            <div className="font-mono text-[10px] px-2 py-0.5 rounded border border-[#1e1e2e] text-gray-500 select-none"
              title={`LLM: ${backendInfo.model}`}>
              {backendInfo.backend === 'groq' ? '⚡ Cloud' : '💻 Local'}
              <span className="ml-1 text-gray-600">{backendInfo.model.split('-')[0]}</span>
            </div>
          )}
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />
            <span className="font-mono text-[10px] text-gray-600">{connected ? 'Connected' : 'Offline'}</span>
          </div>
          {/* Theme toggle */}
          <button
            onClick={() => setDarkMode(d => !d)}
            title={darkMode ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
            className="font-mono text-[13px] text-gray-500 hover:text-gray-300 transition-colors
              px-2.5 py-1 rounded-lg border border-[#1e1e2e] hover:border-[#2e2e45]"
          >
            {darkMode ? '☀' : '☾'}
          </button>
          <button
            onClick={() => window.close()}
            title="Quit MatchCaster"
            className="font-mono text-[11px] text-gray-600 hover:text-red-400 transition-colors
              px-3 py-1 rounded-lg border border-[#1e1e2e] hover:border-red-500/40"
          >
            Quit
          </button>
        </div>
      </div>

      {/* ── Main area ─────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Pitch — full height, 3:2 aspect ratio centred */}
        <div
          className="flex-1 min-w-0 flex items-center justify-center overflow-hidden"
          style={{ background: 'var(--bg-main)' }}
        >
          <div
            className="relative h-full"
            style={{ aspectRatio: '3/2', maxWidth: '100%' }}
          >
            {!selectedMatch ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-8">
                <div className="text-6xl opacity-20">⚽</div>
                <p className="font-mono text-gray-600 text-sm">
                  Click <span className="text-amber-400">MATCHCASTER</span> above to pick a match
                </p>
              </div>
            ) : (
              <>
                <PitchCanvas
                  markers={markers}
                  possessionTrail={activePossession ?? lastPossession ?? []}
                  isActivePossession={activePossession !== null}
                  matchSpeed={speed}
                  dangerEntries={dangerEntries}
                  homeTeam={homeTeam}
                  awayTeam={awayTeam}
                  overlays={overlays}
                  lineup={lineup}
                  heatmapData={heatmapTeam === 'home' ? heatmapHome : heatmapAway}
                  heatmapTeam={heatmapTeam}
                  heatmapGranularity={heatmapGranularity}
                  shots={analysis?.shots ?? []}
                  buildUpVectors={analysis?.build_up_vectors ?? {}}
                  homeColorPrimary={homeColor}
                  homeColorSecondary={homeColorSecondary}
                  awayColorPrimary={awayColor}
                  awayColorSecondary={awayColorSecondary}
                />
                {goalFlash && <GoalFlashOverlay key={goalFlash.key} flash={goalFlash} />}
                <CommentaryOverlay
                  latestCommentary={latestCommentary}
                  activeAgent={activeAgent}
                  isPlaying={isPlaying}
                />
                <OverlayPanel
                  isOpen={showOverlay}
                  overlays={overlays}
                  heatmapTeam={heatmapTeam}
                  heatmapGranularity={heatmapGranularity}
                  personality={personality}
                  homeTeam={homeTeam}
                  awayTeam={awayTeam}
                  onClose={() => setShowOverlay(false)}
                  onToggleOverlay={toggleOverlay}
                  onHeatmapTeamChange={setHeatmapTeam}
                  onHeatmapGranularityChange={setHeatmapGranularity}
                  onPersonalityChange={handlePersonalityChange}
                />
              </>
            )}
          </div>
        </div>

        {/* Sidebar — compact score header + stats/live/squad tabs */}
        <aside
          className="w-80 flex-shrink-0 border-l border-[#1e1e2e] flex flex-col"
          style={{ background: 'var(--bg-panel)' }}
        >
          <SidebarTabs
            matchState={matchState}
            recentEvents={recentEvents}
            analysis={analysis}
            lineup={lineup}
            homeTeam={homeTeam}
            awayTeam={awayTeam}
            homeColor={homeColor}
            awayColor={awayColor}
            score={score}
            matchTime={matchTime}
            displayTime={displayTime}
            running={running}
            matchEnded={matchEnded}
            currentPeriod={currentPeriod}
            goalEvents={goalEvents}
            matchMeta={matchMeta}
          />
        </aside>
      </div>

      {/* ── Video controls ────────────────────────────────────────── */}
      <VideoControls
        running={running}
        speed={speed}
        matchTime={matchTime}
        totalTime={totalTime}
        currentPeriod={currentPeriod}
        matchEnded={matchEnded}
        connected={connected}
        ttsReady={ttsReady}
        muted={muted}
        homeColor={homeColor}
        awayColor={awayColor}
        activityBuckets={activityBuckets}
        goalMarkers={goalMarkers}
        summaryLoading={summaryLoading}
        homeTeam={homeTeam}
        overlays={overlays}
        onToggleOverlay={toggleOverlay}
        onPlay={handlePlay}
        onPause={handlePause}
        onSeek={handleSeek}
        onSpeedChange={handleSpeedChange}
        onMuteToggle={() => setMuted(!muted)}
        onOpenOverlay={() => setShowOverlay(true)}
        onChangeMatch={() => setShowModal(true)}
      />

      {IS_DEV && (
        <DevPanel
          traces={debugTraces}
          onForceTrigger={() => sendAction('force_commentary')}
        />
      )}
    </div>
  )
}
