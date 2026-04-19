// frontend/src/utils/types.ts

export interface MatchEventData {
  id: string
  timestamp_sec: number
  event_type: string
  team: string
  player: string
  position: [number, number]
  end_position: [number, number] | null
  priority: 'critical' | 'notable' | 'routine'
  detected_patterns: string[]
  details: {
    shot_outcome?: string
    pass_outcome?: string
    pass_recipient?: string
    foul_card?: string
    card?: string
    sub_replacement?: string
    minute?: number
    second?: number
    period?: number
    cross?: boolean
    goal_assist?: boolean
    dribble_outcome?: string
    gk_type?: string
    gk_outcome?: string
    xg?: number
  }
}

export interface TeamStats {
  shots: number
  shots_on_target: number
  passes_completed: number
  passes_attempted: number
  fouls: number
  yellow_cards: number
  red_cards: number
  goals: number
  xg: number
}

export interface MatchState {
  score: { home: number; away: number }
  home_team: string
  away_team: string
  match_time: number
  minute: string
  phase: 'open_play' | 'set_piece' | 'stoppage'
  possession: Record<string, number>
  stats: Record<string, TeamStats>
}

export type AgentName = 'play_by_play' | 'tactical' | 'stats'
export type Personality = 'neutral' | 'enthusiastic' | 'analytical' | 'home_bias' | 'away_bias'
export type HeatmapTeam = 'home' | 'away'
export type PitchView = 'pitch' | 'formation' | 'heatmap' | 'shotmap' | 'vectors'

export interface PitchOverlays {
  live: boolean
  formation: boolean
  heatmap: boolean
  shotmap: boolean
  vectors: boolean
}

export interface ShotData {
  player: string
  team: string
  position: [number, number]
  xg: number
  outcome: string   // Goal / Saved / Blocked / Off T / Wayward
  timestamp_sec: number
}

export interface BuildUpZone {
  dx: number
  dy: number
  count: number
}

export interface MatchAnalysis {
  momentum_home: number
  momentum_away: number
  xg_home: number
  xg_away: number
  shots: ShotData[]
  build_up_vectors: Record<string, Record<string, BuildUpZone>>  // team → zone → vector
  dangerous_entries: Record<string, number>
}

export interface CommentaryMessage {
  type: 'commentary'
  agent: AgentName
  text: string
  has_audio: boolean
  match_time: number
}

export interface AudioMessage {
  type: 'audio'
  agent: AgentName
  text: string
  match_time: number
  audio_b64?: string
  audio_format?: 'wav'
}

export interface ClockMessage {
  type: 'clock'
  match_time: number
  speed: number
  running: boolean
  state?: MatchState
  analysis?: MatchAnalysis
}

export interface EventMessage {
  type: 'event'
  data: MatchEventData
  state: MatchState
}

export interface StateMessage {
  type: 'state'
  state: MatchState
  clock: { match_time: number; speed: number; running: boolean }
  match_id: string
  nickname_map?: Record<string, string>
  match_meta?: MatchMeta
}

export interface MatchMeta {
  competition?: string
  season?: string
  date?: string
  kick_off?: string
  stadium?: string
  city?: string
  country?: string
  home_manager?: string
  away_manager?: string
  weather?: string            // e.g. "22°C, light breeze"
  home_colors?: { primary: string; secondary: string }
  away_colors?: { primary: string; secondary: string }
}

export interface ErrorMessage { type: 'error'; message: string }
export interface PingMessage { type: 'ping' }
export interface MatchEndMessage { type: 'match_end'; match_time: number }

export type WsMessage =
  | CommentaryMessage
  | AudioMessage
  | ClockMessage
  | EventMessage
  | StateMessage
  | ErrorMessage
  | PingMessage
  | MatchEndMessage

export interface PitchMarker {
  id: string
  position: [number, number]
  end_position: [number, number] | null
  event_type: string
  team: string
  priority: string
  age: number
  timestamp: number
  details?: Record<string, unknown>
}

export interface MatchInfo {
  match_id: string
  teams: string[]
  event_count: number
  file: string
  total_time: number  // estimated match duration in seconds
}

export interface ActivityBucket {
  t: number       // bucket start in seconds
  home: number    // event count for home team
  away: number    // event count for away team
}

export interface GoalMarker {
  timestamp_sec: number
  team: string
  player: string
}

export interface MatchSummary {
  home_team: string
  goals: GoalMarker[]
  buckets: ActivityBucket[]
  total_time: number
}

export interface LineupPlayer {
  name: string
  jersey_number: number
  position: string
  x: number   // StatsBomb coords (0-120)
  y: number   // StatsBomb coords (0-80)
  goals: number
  assists: number
  team: 'home' | 'away'
  teamColor: string
}

export interface GoalEvent {
  player: string
  team: string
  minute: number
  is_own_goal: boolean
}

// ---------------------------------------------------------------------------
// Developer Inspector types (only used when ?dev=true)
// ---------------------------------------------------------------------------

export interface PipelineTriggerEvent {
  type: string
  player: string
  team: string
}

export interface PipelineTrace {
  trace_id: string
  wall_time: number
  // Trigger
  trigger_events: PipelineTriggerEvent[]
  classification: 'CRITICAL' | 'NOTABLE' | 'ROUTINE' | 'dead-air' | 'follow_up'
  agent_selected: string
  selection_reason: string
  // 4 prompt layers
  layer_general_context: string   // system prompt (role + personality)
  layer_match_context: string     // score, minute, phase, possession, shots
  layer_recent_play: string       // last 3 utterances (what not to repeat)
  layer_immediate: string         // triggering event(s) text
  user_prompt_assembled: string   // full user turn as sent to Ollama
  // LLM output
  llm_raw_response: string
  llm_cleaned_text: string
  llm_token_count: number
  llm_generation_ms: number
  llm_used_fallback: boolean
  // TTS
  tts_voice: string
  tts_backend: 'piper' | 'say' | 'none' | ''
  tts_synthesis_ms: number
  tts_audio_duration_sec: number
  // End-to-end
  end_to_end_ms: number
}

export interface DebugMessage {
  type: 'debug'
  trace: PipelineTrace
}

export type WsMessageWithDebug = WsMessage | DebugMessage
