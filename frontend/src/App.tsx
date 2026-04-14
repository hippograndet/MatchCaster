// frontend/src/App.tsx

import React, { useState, useEffect, useCallback } from 'react'
import { PitchCanvas } from './components/PitchCanvas'
import type { PassTrailPoint, DangerEntry } from './components/PitchCanvas'
import { MatchHeader } from './components/MatchHeader'
import { SidebarTabs } from './components/SidebarTabs'
import { VideoControls } from './components/VideoControls'
import { OverlayPanel } from './components/OverlayPanel'
import { MatchSelectModal } from './components/MatchSelectModal'
import { CommentaryOverlay } from './components/CommentaryOverlay'
import DevPanel from './components/DevPanel'
import { useWebSocket } from './hooks/useWebSocket'
import type { AgentCommentary } from './hooks/useWebSocket'
import { useAudioPlayer } from './hooks/useAudioPlayer'
import type {
  PitchMarker, PitchOverlays, Personality, HeatmapTeam, LineupPlayer, MatchInfo,
  ActivityBucket, GoalMarker,
} from './utils/types'

const IS_DEV = new URLSearchParams(window.location.search).has('dev')

const MARKER_MAX_AGE_MS = 10_000
const TRAIL_MAX_MS      = 14_000

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

export default function App() {
  // ── UI state ──────────────────────────────────────────────────────────
  const [showModal,   setShowModal]   = useState(true)
  const [showOverlay, setShowOverlay] = useState(false)

  // ── Match selection ───────────────────────────────────────────────────
  const [selectedMatch, setSelectedMatch] = useState<string | null>(null)
  const [totalTime,     setTotalTime]     = useState(5400)   // seconds

  // ── Pitch state ───────────────────────────────────────────────────────
  const [overlays, setOverlays] = useState<PitchOverlays>({
    live: true, formation: false, heatmap: false, shotmap: false, vectors: false,
  })
  const [heatmapTeam,       setHeatmapTeam]       = useState<HeatmapTeam>('home')
  const [heatmapGranularity,setHeatmapGranularity]= useState(4)
  const [personality,       setPersonality]       = useState<Personality>('neutral')
  const [markers,           setMarkers]           = useState<PitchMarker[]>([])
  const [passTrail,         setPassTrail]         = useState<PassTrailPoint[]>([])
  const [dangerEntries,     setDangerEntries]     = useState<DangerEntry[]>([])
  const [lineup,            setLineup]            = useState<LineupPlayer[]>([])
  const [heatmapHome,       setHeatmapHome]       = useState<number[][]>(emptyGrid)
  const [heatmapAway,       setHeatmapAway]       = useState<number[][]>(emptyGrid)
  const [activityBuckets,   setActivityBuckets]   = useState<ActivityBucket[]>([])
  const [goalMarkers,       setGoalMarkers]       = useState<GoalMarker[]>([])
  const [summaryLoading,    setSummaryLoading]    = useState(false)

  // ── WebSocket ─────────────────────────────────────────────────────────
  const {
    connected, matchState, matchTime, speed, running, matchEnded, currentPeriod,
    recentEvents, goalEvents, matchMeta, analysis,
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

  // ── Derived colors ────────────────────────────────────────────────────
  const homeColor = matchMeta?.home_colors?.primary ?? '#22c55e'
  const awayColor = matchMeta?.away_colors?.primary ?? '#3b82f6'
  const homeTeam  = matchState?.home_team ?? 'Home'
  const awayTeam  = matchState?.away_team ?? 'Away'
  const score     = matchState?.score ?? { home: 0, away: 0 }

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

    if (latest.event_type === 'Pass' && latest.end_position) {
      const pt: PassTrailPoint = { from: latest.position, to: latest.end_position, team: latest.team, timestamp: now }
      setPassTrail(prev => [...prev.filter(p => now - p.timestamp < TRAIL_MAX_MS), pt])
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
    const row = Math.min(HEATMAP_ROWS - 1, Math.floor((y / 80)  * HEATMAP_ROWS))
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
  const handleSeek        = useCallback((t: number) => sendAction('seek', { target_time: t }), [sendAction])
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
    // Reset all pitch state
    setMarkers([]); setPassTrail([]); setDangerEntries([]); setLineup([])
    setHeatmapHome(emptyGrid()); setHeatmapAway(emptyGrid())
    setActivityBuckets([]); setGoalMarkers([])
    setOverlays({ live: true, formation: false, heatmap: false, shotmap: false, vectors: false })
    setPersonality(pers)
    setSelectedMatch(matchId)
    // Fetch total time for seek bar
    fetch('/api/matches')
      .then(r => r.json())
      .then((ms: MatchInfo[]) => {
        const m = ms.find(x => x.match_id === matchId)
        if (m) setTotalTime(m.total_time ?? 5400)
      })
      .catch(() => {})
    // Fetch match summary for waveform
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
    <div className="flex flex-col h-screen bg-[#0a0a12] text-gray-100 overflow-hidden">

      {/* ── Launch modal ─────────────────────────────────────────── */}
      {showModal && <MatchSelectModal onStart={handleStart} />}

      {/* ── Top bar ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[#1e1e2e] bg-[#080810] flex-shrink-0">
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
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />
            <span className="font-mono text-[10px] text-gray-600">{connected ? 'Connected' : 'Offline'}</span>
          </div>
        </div>
      </div>

      {/* ── Match header ─────────────────────────────────────────── */}
      <MatchHeader
        homeTeam={homeTeam}
        awayTeam={awayTeam}
        score={score}
        matchTime={matchTime}
        running={running}
        matchEnded={matchEnded}
        goalEvents={goalEvents}
        matchMeta={matchMeta}
        homeColor={homeColor}
        awayColor={awayColor}
      />

      {/* ── Main area ─────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Pitch */}
        <div className="flex-1 min-w-0 relative bg-[#07070e]">
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
                passTrail={passTrail}
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
              />
              <CommentaryOverlay
                latestCommentary={latestCommentary}
                activeAgent={activeAgent}
                isPlaying={isPlaying}
              />
              {/* Overlay panel — floats top-right of pitch */}
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

        {/* Sidebar */}
        <aside className="w-80 flex-shrink-0 border-l border-[#1e1e2e] bg-[#080810]">
          <SidebarTabs
            matchState={matchState}
            recentEvents={recentEvents}
            analysis={analysis}
            lineup={lineup}
            homeTeam={homeTeam}
            awayTeam={awayTeam}
            homeColor={homeColor}
            awayColor={awayColor}
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
        muted={muted}
        homeColor={homeColor}
        awayColor={awayColor}
        activityBuckets={activityBuckets}
        goalMarkers={goalMarkers}
        summaryLoading={summaryLoading}
        homeTeam={homeTeam}
        onPlay={handlePlay}
        onPause={handlePause}
        onSeek={handleSeek}
        onSpeedChange={handleSpeedChange}
        onMuteToggle={() => setMuted(!muted)}
        onOpenOverlay={() => setShowOverlay(true)}
        onChangeMatch={() => setShowModal(true)}
      />

      {/* Dev inspector — only rendered when ?dev=true */}
      {IS_DEV && <DevPanel traces={debugTraces} />}
    </div>
  )
}
