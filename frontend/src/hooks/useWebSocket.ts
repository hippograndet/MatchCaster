// frontend/src/hooks/useWebSocket.ts

import { useEffect, useRef, useCallback, useState } from 'react'
import type {
  MatchState,
  MatchEventData,
  AgentName,
  AudioMessage,
  GoalEvent,
  MatchMeta,
  MatchAnalysis,
  Personality,
  PipelineTrace,
} from '../utils/types'

const IS_DEV = new URLSearchParams(window.location.search).has('dev')

const WS_BASE = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'
const RECONNECT_DELAY_MS = 2000

export interface AgentCommentary {
  agent: AgentName
  text: string
  match_time: number
  timestamp: number
}

export interface BackendInfo {
  backend: string
  model: string
}

export interface UseWebSocketReturn {
  connected: boolean
  matchState: MatchState | null
  matchTime: number
  displayTime: number
  speed: number
  running: boolean
  matchEnded: boolean
  currentPeriod: number
  recentEvents: MatchEventData[]
  agentCommentaries: Record<AgentName, AgentCommentary | null>
  goalEvents: GoalEvent[]
  matchMeta: MatchMeta | null
  analysis: MatchAnalysis | null
  nicknameMap: Record<string, string>
  ttsReady: boolean
  backendInfo: BackendInfo | null
  setOnAudioReceived: (cb: ((msg: AudioMessage) => void) | null) => void
  sendAction: (action: string, extra?: Record<string, unknown>) => void
  debugTraces: PipelineTrace[]
}

export function useWebSocket(matchId: string | null): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)
  const audioCallbackRef = useRef<((msg: AudioMessage) => void) | null>(null)
  const hasConnectedRef = useRef(false)
  const [ttsReady, setTtsReady] = useState(false)
  const [backendInfo, setBackendInfo] = useState<BackendInfo | null>(null)

  const [connected, setConnected] = useState(false)
  const [matchState, setMatchState] = useState<MatchState | null>(null)
  const [matchTime, setMatchTime] = useState(0)
  const [displayTime, setDisplayTime] = useState(0)
  const [speed, setSpeed] = useState(1)
  const [running, setRunning] = useState(false)
  const [matchEnded, setMatchEnded] = useState(false)
  const [currentPeriod, setCurrentPeriod] = useState(1)
  const [recentEvents, setRecentEvents] = useState<MatchEventData[]>([])
  const [goalEvents, setGoalEvents] = useState<GoalEvent[]>([])
  const [matchMeta, setMatchMeta] = useState<MatchMeta | null>(null)
  const [analysis, setAnalysis] = useState<MatchAnalysis | null>(null)
  const [nicknameMap, setNicknameMap] = useState<Record<string, string>>({})
  const [agentCommentaries, setAgentCommentaries] = useState<
    Record<AgentName, AgentCommentary | null>
  >({ play_by_play: null, tactical: null, stats: null })
  const [debugTraces, setDebugTraces] = useState<PipelineTrace[]>([])

  const setOnAudioReceived = useCallback(
    (cb: ((msg: AudioMessage) => void) | null) => {
      audioCallbackRef.current = cb
    },
    []
  )

  const handleMessage = useCallback((raw: string) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let msg: any
    try { msg = JSON.parse(raw) } catch { return }

    // Developer debug trace — handled before the main switch
    if (IS_DEV && msg.type === 'debug') {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      setDebugTraces(prev => [(msg as any).trace as PipelineTrace, ...prev].slice(0, 100))
      return
    }

    switch (msg.type) {
      case 'state':
        setMatchState(msg.state)
        setMatchTime(msg.clock.match_time)
        setDisplayTime(msg.clock.match_time)
        setSpeed(msg.clock.speed)
        setRunning(msg.clock.running)
        if (msg.nickname_map) setNicknameMap(msg.nickname_map)
        if (msg.match_meta) setMatchMeta(msg.match_meta)
        break

      case 'clock':
        setMatchTime(msg.match_time)
        setDisplayTime(msg.match_time)
        setSpeed(msg.speed)
        setRunning(msg.running)
        if (msg.state) setMatchState(msg.state)
        if (msg.analysis) setAnalysis(msg.analysis)
        break

      case 'event': {
        setMatchState(msg.state)
        const ev = msg.data
        if (ev.details.period) setCurrentPeriod(ev.details.period as number)
        setRecentEvents(prev => [...prev, ev].slice(-200))

        // Track goals for header display
        if (ev.event_type === 'Shot' && ev.details.shot_outcome === 'Goal') {
          setGoalEvents(prev => [
            ...prev,
            {
              player: ev.player,
              team: ev.team,
              minute: Math.floor(ev.timestamp_sec / 60),
              is_own_goal: false,
            },
          ])
        }
        break
      }

      case 'commentary':
      case 'audio': {
        const entry: AgentCommentary = {
          agent: msg.agent,
          text: msg.text,
          match_time: msg.match_time,
          timestamp: Date.now(),
        }
        setAgentCommentaries(prev => ({ ...prev, [msg.agent]: entry }))
        // Route both commentary and audio through audio player so
        // the text/audio overlay is always driven by playback timing
        if (audioCallbackRef.current) {
          audioCallbackRef.current(msg as AudioMessage)
        }
        break
      }

      case 'match_end':
        setMatchEnded(true)
        setRunning(false)
        break

      case 'tts_ready':
        setTtsReady(true)
        break

      case 'backend_status':
        setBackendInfo({ backend: msg.backend, model: msg.model })
        break

      case 'ping':
        break

      case 'error':
        console.error('[WS] Server error:', (msg as { type: 'error'; message: string }).message)
        break
    }
  }, [])

  const connect = useCallback(() => {
    if (!matchId || !mountedRef.current) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const url = `${WS_BASE}/ws/match?match_id=${encodeURIComponent(matchId)}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return }
      hasConnectedRef.current = true
      setConnected(true)
    }
    ws.onmessage = (evt) => handleMessage(evt.data)
    ws.onclose = () => {
      if (!mountedRef.current) return
      setConnected(false)
      setRunning(false)
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS)
    }
    ws.onerror = () => ws.close()
  }, [matchId, handleMessage])

  useEffect(() => {
    mountedRef.current = true
    hasConnectedRef.current = false
    setRecentEvents([])
    setGoalEvents([])
    setMatchEnded(false)
    setCurrentPeriod(1)
    setTtsReady(false)
    setBackendInfo(null)
    setAnalysis(null)
    setAgentCommentaries({ play_by_play: null, tactical: null, stats: null })
    if (matchId) connect()
    return () => {
      mountedRef.current = false
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (wsRef.current) { wsRef.current.onclose = null; wsRef.current.close() }
    }
  }, [matchId, connect])

  // Client-side interpolation: tick displayTime every 100ms when running.
  // Server snapshots (above) correct any drift each 500ms.
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => {
      setDisplayTime(t => t + 0.1 * speed)
    }, 100)
    return () => clearInterval(id)
  }, [running, speed, matchTime])

  const sendAction = useCallback(
    (action: string, extra?: Record<string, unknown>) => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) return
      ws.send(JSON.stringify({ action, match_id: matchId, ...extra }))
    },
    [matchId]
  )

  return {
    connected,
    matchState,
    matchTime,
    displayTime,
    speed,
    running,
    matchEnded,
    currentPeriod,
    recentEvents,
    agentCommentaries,
    goalEvents,
    matchMeta,
    analysis,
    nicknameMap,
    ttsReady,
    backendInfo,
    setOnAudioReceived,
    sendAction,
    debugTraces,
  }
}
