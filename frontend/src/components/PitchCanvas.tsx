// frontend/src/components/PitchCanvas.tsx
// Animated pitch: event markers, chem-trail passes, formation overlay, heatmap

import React, { useRef, useEffect, useCallback } from 'react'
import { drawPitch, sbToCanvas } from '../utils/pitchCoords'
import type { PitchMarker, PitchOverlays, HeatmapTeam, LineupPlayer, ShotData, BuildUpZone } from '../utils/types'

export interface PossessionSegment {
  from: [number, number]
  to: [number, number]
  team: string
  player: string          // last name shown at the start of each segment
  type: 'carry' | 'pass' | 'cross' | 'dribble' | 'shot' | 'transition'
  gameTimeSec: number
  arrivalWallMs: number
  durationMs: number      // real-time ms derived from StatsBomb duration; 0 = use fallback speeds
  possessionId: number
  segmentIndex: number
  outOfPlay?: boolean     // true when this action sent the ball out of bounds
}

export interface DangerEntry {
  position: [number, number]
  team: string
  timestamp: number
}

interface PitchCanvasProps {
  markers: PitchMarker[]
  ballHistory: PossessionSegment[]
  matchSpeed: number
  dangerEntries: DangerEntry[]
  homeTeam: string
  awayTeam: string
  overlays: PitchOverlays
  lineup: LineupPlayer[]
  heatmapData: number[][]
  heatmapTeam?: HeatmapTeam
  heatmapGranularity?: number
  shots: ShotData[]
  buildUpVectors: Record<string, Record<string, BuildUpZone>>
  homeColorPrimary?: string
  homeColorSecondary?: string
  awayColorPrimary?: string
  awayColorSecondary?: string
  className?: string
}

const MARKER_FADE_MS = 8000
const FLASH_DURATION_MS = 700
// Unified ball history: segments fade linearly from when they started animating.
// Anything older than 30s is invisible; pruned from App.tsx at 60s.
const TRAIL_FADE_MS = 30_000

// Fallback travel speeds in StatsBomb units/sec at 1× match speed.
// Used only when no real duration is available from the data.
// SB pitch is 120×80 ≈ 105×68 m, so 1 SB unit ≈ 0.875 m.
// pass 17 SB/s ≈ 15 m/s (54 km/h), shot 30 SB/s ≈ 26 m/s (94 km/h)
const VISUAL_SPEEDS: Partial<Record<PossessionSegment['type'], number>> = {
  pass:    17,   // realistic ground pass
  cross:   20,   // driven cross — slightly faster
  carry:   6,    // jogging with ball (~5 m/s)
  dribble: 4,    // tight twisting run
  shot:    30,   // hard shot
}

const ease = {
  inOut:  (t: number) => t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t,
  out:    (t: number) => 1 - (1 - t) * (1 - t),
  linear: (t: number) => t,
}

function applyEase(seg: PossessionSegment, t: number): number {
  switch (seg.type) {
    case 'carry':      return ease.inOut(t)
    case 'dribble':    return ease.inOut(t)
    case 'pass':       return ease.out(t)
    case 'cross':      return ease.out(t)
    case 'shot':       return ease.linear(t)
    case 'transition': return ease.out(t)
    default:           return ease.out(t)
  }
}
const HOME_COLOR = '#22c55e'
const AWAY_COLOR = '#3b82f6'
const PADDING = 28

const EVENT_COLORS: Record<string, string> = {
  shot_goal:       '#ef4444',
  shot_saved:      '#f97316',
  shot:            '#fbbf24',
  pass:            'rgba(255,255,255,0.45)',
  cross:           '#a78bfa',
  dribble:         '#60a5fa',
  foul:            '#f43f5e',
  card:            '#dc2626',
  turnover:        '#fb923c',
  block:           '#94a3b8',
  save:            '#06b6d4',
  default:         'rgba(180,180,180,0.3)',
}

const DANGER_FLASH_MS = 3000

// ---- Shot map ----
function drawShotMap(
  ctx: CanvasRenderingContext2D,
  shots: ShotData[],
  homeTeam: string,
  width: number,
  height: number,
  padding: number
) {
  for (const shot of shots) {
    const { x, y } = sbToCanvas(shot.position[0], shot.position[1], width, height, padding)
    const isHome = shot.team === homeTeam
    const outcome = shot.outcome
    const r = Math.max(5, Math.min(18, 5 + shot.xg * 40))
    let fillColor: string
    if (outcome === 'Goal') fillColor = 'rgba(239,68,68,0.85)'
    else if (outcome === 'Saved') fillColor = 'rgba(251,191,36,0.7)'
    else if (outcome === 'Blocked') fillColor = 'rgba(148,163,184,0.6)'
    else fillColor = 'rgba(100,116,139,0.4)'

    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fillStyle = fillColor
    ctx.fill()
    ctx.strokeStyle = isHome ? HOME_COLOR : AWAY_COLOR
    ctx.lineWidth = outcome === 'Goal' ? 2.5 : 1.5
    ctx.stroke()

    if (shot.xg > 0.2) {
      ctx.fillStyle = 'rgba(255,255,255,0.9)'
      ctx.font = `bold ${Math.max(7, Math.min(10, r - 2))}px monospace`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(shot.xg.toFixed(2), x, y)
    }
  }
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'

  // Legend
  const legend = [
    { label: 'Goal', color: 'rgba(239,68,68,0.85)' },
    { label: 'Saved', color: 'rgba(251,191,36,0.7)' },
    { label: 'Blocked', color: 'rgba(148,163,184,0.6)' },
    { label: 'Off target', color: 'rgba(100,116,139,0.4)' },
  ]
  ctx.font = '9px monospace'
  legend.forEach((l, i) => {
    const lx = padding + 4, ly = padding + 10 + i * 14
    ctx.beginPath(); ctx.arc(lx + 5, ly, 5, 0, Math.PI * 2)
    ctx.fillStyle = l.color; ctx.fill()
    ctx.fillStyle = 'rgba(255,255,255,0.7)'
    ctx.fillText(l.label, lx + 13, ly + 3)
  })
}

// ---- Build-up vector arrows (6×4 zone grid) ----
function drawBuildUpVectors(
  ctx: CanvasRenderingContext2D,
  vectors: Record<string, Record<string, BuildUpZone>>,
  homeTeam: string,
  width: number,
  height: number,
  padding: number
) {
  const COLS = 6, ROWS = 4
  const cellW = (width - padding * 2) / COLS
  const cellH = (height - padding * 2) / ROWS
  let maxCount = 1
  for (const zones of Object.values(vectors))
    for (const z of Object.values(zones))
      if (z.count > maxCount) maxCount = z.count

  for (const [team, zones] of Object.entries(vectors)) {
    const isHome = team === homeTeam
    const rgb = isHome ? '34,197,94' : '59,130,246'
    for (const [zk, zv] of Object.entries(zones)) {
      if (zv.count < 3) continue
      const [colStr, rowStr] = zk.split(',')
      const col = parseInt(colStr), row = parseInt(rowStr)
      const cx = padding + (col + 0.5) * cellW
      const cy = padding + (row + 0.5) * cellH
      const mag = Math.sqrt(zv.dx * zv.dx + zv.dy * zv.dy)
      if (mag < 0.5) continue
      const alpha = Math.min(0.9, 0.2 + (zv.count / maxCount) * 0.7)
      const scaleX = (width - padding * 2) / 120
      const scaleY = (height - padding * 2) / 80
      const arrowLen = Math.min(35, Math.max(10, mag * Math.min(scaleX, scaleY) * 0.6))
      const nx = (zv.dx / mag) * arrowLen
      const ny = -(zv.dy / mag) * arrowLen  // flip y for canvas
      const ex = cx + nx, ey = cy + ny
      const angle = Math.atan2(ey - cy, ex - cx)
      const al = 8

      ctx.save()
      ctx.globalAlpha = alpha
      ctx.strokeStyle = `rgba(${rgb},1)`
      ctx.lineWidth = 1.5 + (zv.count / maxCount) * 2
      ctx.lineCap = 'round'
      ctx.shadowColor = `rgba(${rgb},0.4)`; ctx.shadowBlur = 4
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(ex, ey); ctx.stroke()
      ctx.fillStyle = `rgba(${rgb},1)`; ctx.shadowBlur = 0
      ctx.beginPath()
      ctx.moveTo(ex, ey)
      ctx.lineTo(ex - al * Math.cos(angle - Math.PI / 5), ey - al * Math.sin(angle - Math.PI / 5))
      ctx.lineTo(ex - al * Math.cos(angle + Math.PI / 5), ey - al * Math.sin(angle + Math.PI / 5))
      ctx.closePath(); ctx.fill()
      ctx.restore()
    }
  }
}

// ---- Dangerous entry flash ----
function drawDangerEntries(
  ctx: CanvasRenderingContext2D,
  entries: DangerEntry[],
  homeTeam: string,
  width: number,
  height: number,
  padding: number
) {
  const now = Date.now()
  for (const entry of entries) {
    const age = now - entry.timestamp
    if (age > DANGER_FLASH_MS) continue
    const t = age / DANGER_FLASH_MS
    const opacity = Math.pow(1 - t, 1.5)
    const radius = 10 + t * 30
    const { x, y } = sbToCanvas(entry.position[0], entry.position[1], width, height, padding)
    const rgb = entry.team === homeTeam ? '34,197,94' : '59,130,246'

    ctx.save()
    ctx.globalAlpha = opacity * 0.7
    ctx.strokeStyle = `rgba(${rgb},1)`; ctx.lineWidth = 2
    ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.stroke()
    ctx.globalAlpha = opacity
    ctx.fillStyle = `rgba(${rgb},0.9)`
    ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill()
    ctx.restore()
  }
}

// ---- Formation positions — home team left half (x: 4–55), away is mirror (65–116)
const POSITION_MAP: Record<string, [number, number]> = {
  'Goalkeeper':               [4,  40],
  'Center Back':              [18, 40],
  'Left Center Back':         [18, 52],
  'Right Center Back':        [18, 28],
  'Left Back':                [16, 68],
  'Right Back':               [16, 12],
  'Left Wing Back':           [26, 72],
  'Right Wing Back':          [26, 8],
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
  'Right Wing':               [51, 8],
  'Secondary Striker':        [51, 40],
}

function getFormationCoords(position: string, team: 'home' | 'away'): [number, number] {
  const base = POSITION_MAP[position] ?? [38, 40]
  if (team === 'away') return [120 - base[0], 80 - base[1]]
  return base
}

function getMarkerColor(m: PitchMarker): string {
  const et = m.event_type.toLowerCase()
  const d = m.details as Record<string, string | boolean | undefined> | undefined
  const outcome = (typeof d?.shot_outcome === 'string' ? d.shot_outcome.toLowerCase() : '') ?? ''
  if (et === 'shot') {
    if (outcome === 'goal') return EVENT_COLORS.shot_goal
    if (outcome.includes('saved')) return EVENT_COLORS.shot_saved
    return EVENT_COLORS.shot
  }
  if (et === 'pass') return d?.cross ? EVENT_COLORS.cross : EVENT_COLORS.pass
  if (et === 'dribble') return EVENT_COLORS.dribble
  if (et.includes('foul')) return EVENT_COLORS.foul
  if (et.includes('bad behaviour')) return EVENT_COLORS.card
  if (et === 'block') return EVENT_COLORS.block
  if (et === 'goal keeper') return EVENT_COLORS.save
  return EVENT_COLORS.default
}

// Returns how many real-time milliseconds it takes to visually traverse a segment.
// Prefers the real StatsBomb duration (already speed-adjusted in App.tsx).
// Falls back to distance ÷ realistic speed constant when duration is missing.
function segVisualDurationMs(seg: PossessionSegment, matchSpeed: number): number {
  if (seg.durationMs > 0) return Math.max(60, seg.durationMs)
  const dx = seg.to[0] - seg.from[0]
  const dy = seg.to[1] - seg.from[1]
  const dist = Math.sqrt(dx * dx + dy * dy)
  const speed = (VISUAL_SPEEDS[seg.type as keyof typeof VISUAL_SPEEDS] ?? 6) * Math.max(0.25, matchSpeed)
  return Math.max(60, (dist / speed) * 1000)
}

// ---- Unified ball history ----
// Renders a single continuous ball trail across all possessions and transitions.
// Segments are sequenced using effStart = max(arrivalWallMs, prevSegEnd) so that
// delivery jitter never causes two segments to animate simultaneously.
function drawBallHistory(
  ctx: CanvasRenderingContext2D,
  history: PossessionSegment[],
  matchSpeed: number,
  homeTeam: string,
  width: number,
  height: number,
  padding: number
) {
  if (history.length === 0) return
  const now = Date.now()

  // Walk history computing effective start time for each segment.
  // effStart ensures animation is always sequential, regardless of arrival order.
  let lastSegEnd = 0
  const effStarts: number[] = []
  for (const seg of history) {
    const effStart = Math.max(seg.arrivalWallMs, lastSegEnd)
    effStarts.push(effStart)
    lastSegEnd = effStart + segVisualDurationMs(seg, matchSpeed)
  }

  // ── Draw trail lines ────────────────────────────────────────────────────
  for (let i = 0; i < history.length; i++) {
    const seg = history[i]
    const effStart = effStarts[i]
    const age = now - effStart
    if (age < 0) continue  // not yet started

    // Opacity fades linearly from when the segment started animating
    const trailOpacity = Math.max(0, 1 - age / TRAIL_FADE_MS)
    if (trailOpacity < 0.02) continue

    const { x: x1, y: y1 } = sbToCanvas(seg.from[0], seg.from[1], width, height, padding)
    const { x: x2, y: y2 } = sbToCanvas(seg.to[0], seg.to[1], width, height, padding)

    // Transition segments: thin muted dashed connector, no arrowhead or label
    if (seg.type === 'transition') {
      ctx.save()
      ctx.globalAlpha = trailOpacity * (seg.outOfPlay ? 0.12 : 0.22)
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 1
      ctx.lineCap = 'round'
      ctx.setLineDash([2, 8])
      ctx.beginPath()
      ctx.moveTo(x1, y1)
      ctx.lineTo(x2, y2)
      ctx.stroke()
      ctx.setLineDash([])
      ctx.restore()
      continue
    }

    const isHome = seg.team === homeTeam
    const teamRgb = isHome ? '34,197,94' : '59,130,246'

    let lineWidth: number
    let lineDash: number[]
    let alphaModifier = 1.0

    switch (seg.type) {
      case 'carry':
        lineWidth = 1.5; lineDash = [4, 5]; alphaModifier = 0.65; break
      case 'cross':
        lineWidth = 2.0; lineDash = [6, 4]; break
      case 'dribble':
        lineWidth = 2.0; lineDash = [2, 3]; break
      case 'shot':
        lineWidth = 2.0; lineDash = [3, 3]; alphaModifier = 0.9; break
      case 'pass':
      default:
        lineWidth = 1.5 + trailOpacity * 0.5; lineDash = []; break
    }

    ctx.save()
    ctx.globalAlpha = trailOpacity * alphaModifier
    ctx.strokeStyle = `rgb(${teamRgb})`
    ctx.lineWidth = lineWidth
    ctx.lineCap = 'round'
    ctx.setLineDash(lineDash)
    ctx.shadowColor = `rgba(${teamRgb},0.4)`
    ctx.shadowBlur = 2 + trailOpacity * 5
    ctx.beginPath()
    ctx.moveTo(x1, y1)
    ctx.lineTo(x2, y2)
    ctx.stroke()
    ctx.setLineDash([])

    // Arrowhead on passes, crosses, and shots
    if ((seg.type === 'pass' || seg.type === 'cross' || seg.type === 'shot') && trailOpacity > 0.2) {
      const angle = Math.atan2(y2 - y1, x2 - x1)
      const al = 5 + trailOpacity * 2
      ctx.globalAlpha = trailOpacity
      ctx.shadowBlur = 0
      ctx.fillStyle = `rgb(${teamRgb})`
      ctx.beginPath()
      ctx.moveTo(x2, y2)
      ctx.lineTo(x2 - al * Math.cos(angle - Math.PI / 6), y2 - al * Math.sin(angle - Math.PI / 6))
      ctx.lineTo(x2 - al * Math.cos(angle + Math.PI / 6), y2 - al * Math.sin(angle + Math.PI / 6))
      ctx.closePath()
      ctx.fill()
    }

    // Player last name at the from point — shown while segment is fresh
    if (trailOpacity > 0.35 && seg.player) {
      const lastName = seg.player.trim().split(/\s+/).pop() ?? seg.player
      ctx.shadowBlur = 0
      ctx.font = 'bold 8px monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'bottom'
      const textW = ctx.measureText(lastName).width
      ctx.globalAlpha = trailOpacity * 0.9
      ctx.fillStyle = 'rgba(0,0,0,0.65)'
      ctx.fillRect(x1 - textW / 2 - 2, y1 - 12, textW + 4, 10)
      ctx.fillStyle = `rgb(${teamRgb})`
      ctx.fillText(lastName, x1, y1 - 2)
    }

    // OUT badge at endpoint — marks where the ball left the field
    if (seg.outOfPlay && trailOpacity > 0.1) {
      ctx.shadowBlur = 0
      ctx.font = 'bold 7px monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      const label = 'OUT'
      const lw = ctx.measureText(label).width + 6
      ctx.globalAlpha = trailOpacity * 0.85
      ctx.fillStyle = 'rgba(0,0,0,0.7)'
      ctx.beginPath()
      ctx.roundRect(x2 - lw / 2, y2 - 7, lw, 14, 3)
      ctx.fill()
      ctx.strokeStyle = 'rgba(255,255,255,0.5)'
      ctx.lineWidth = 0.5
      ctx.stroke()
      ctx.fillStyle = '#ffffff'
      ctx.fillText(label, x2, y2)
    }

    ctx.restore()
  }

  // ── Single animated ball dot ────────────────────────────────────────────
  // Walk segments to find where the ball is right now.
  // Default to last segment at progress=1.0 (ball at rest after all known events).
  let ballSeg = history[history.length - 1]
  let ballProgress = 1.0
  let ballFound = false

  for (let i = 0; i < history.length; i++) {
    const seg = history[i]
    const effStart = effStarts[i]
    const dur = segVisualDurationMs(seg, matchSpeed)
    const age = now - effStart

    if (age >= 0 && age < dur) {
      ballSeg = seg
      ballProgress = age / dur
      ballFound = true
      break
    }
  }

  const { x: x1, y: y1 } = sbToCanvas(ballSeg.from[0], ballSeg.from[1], width, height, padding)
  const { x: x2, y: y2 } = sbToCanvas(ballSeg.to[0], ballSeg.to[1], width, height, padding)
  const bx = x1 + (x2 - x1) * applyEase(ballSeg, ballProgress)
  const by = y1 + (y2 - y1) * applyEase(ballSeg, ballProgress)

  const pastEnd = !ballFound  // no in-progress segment — ball at rest
  const pulseR = pastEnd ? 3 + 1.5 * Math.abs(Math.sin(now * 0.004)) : 2.5

  const isHome = ballSeg.team === homeTeam
  const teamRgb = isHome ? '34,197,94' : '59,130,246'

  ctx.save()
  ctx.shadowColor = `rgb(${teamRgb})`
  ctx.shadowBlur = 12
  ctx.globalAlpha = 0.5
  ctx.beginPath()
  ctx.arc(bx, by, pulseR + 2.5, 0, Math.PI * 2)
  ctx.fillStyle = `rgb(${teamRgb})`
  ctx.fill()
  ctx.shadowBlur = 0
  ctx.globalAlpha = 1.0
  ctx.beginPath()
  ctx.arc(bx, by, pulseR, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.restore()
}

// ---- Heatmap ----
// Takes the raw 24×16 grid and aggregates to 2^granularity bins per axis
function drawHeatmap(
  ctx: CanvasRenderingContext2D,
  data: number[][],
  width: number,
  height: number,
  padding: number,
  granularity: number = 4
) {
  const pitchW = width - padding * 2
  const pitchH = height - padding * 2
  const srcRows = data.length
  const srcCols = data[0]?.length ?? 0
  if (srcRows === 0 || srcCols === 0) return

  // Target bins: 2^granularity (clamped to source resolution)
  const binsX = Math.min(srcCols, Math.pow(2, granularity))
  const binsY = Math.min(srcRows, Math.round(Math.pow(2, granularity) * srcRows / srcCols))

  // Aggregate source cells into bins
  const binned: number[][] = Array.from({ length: binsY }, () => new Array(binsX).fill(0))
  for (let r = 0; r < srcRows; r++) {
    for (let c = 0; c < srcCols; c++) {
      const br = Math.floor(r * binsY / srcRows)
      const bc = Math.floor(c * binsX / srcCols)
      binned[br][bc] += data[r][c]
    }
  }

  const maxVal = Math.max(1, ...binned.flat())
  const cellW = pitchW / binsX
  const cellH = pitchH / binsY

  for (let r = 0; r < binsY; r++) {
    for (let c = 0; c < binsX; c++) {
      const val = binned[r][c]
      // Always draw a faint base so the full grid is visible even at zero
      const intensity = val === 0 ? 0 : Math.min(1, val / (maxVal * 0.7))
      const lightness  = Math.round(val === 0 ? 90 : 85 - intensity * 60)
      const saturation = Math.round(val === 0 ? 20 : 30 + intensity * 70)
      const alpha      = val === 0 ? 0.06 : (0.10 + intensity * 0.65)
      ctx.fillStyle = `hsla(215, ${saturation}%, ${lightness}%, ${alpha})`
      ctx.fillRect(
        padding + c * cellW,
        padding + r * cellH,
        cellW,
        cellH
      )
    }
  }
}

// ---- Formation ----
function drawFormation(
  ctx: CanvasRenderingContext2D,
  lineup: LineupPlayer[],
  width: number,
  height: number,
  padding: number,
  homePrimary: string,
  homeSecondary: string,
  awayPrimary: string,
  awaySecondary: string,
) {
  for (const player of lineup) {
    const [sbX, sbY] = getFormationCoords(player.position, player.team)
    const { x, y } = sbToCanvas(sbX, sbY, width, height, padding)
    const primary   = player.team === 'home' ? homePrimary   : awayPrimary
    const secondary = player.team === 'home' ? homeSecondary : awaySecondary
    const r = 13

    // Outer glow + secondary-color ring
    ctx.save()
    ctx.shadowColor = primary
    ctx.shadowBlur = 10
    ctx.beginPath()
    ctx.arc(x, y, r + 3, 0, Math.PI * 2)
    ctx.strokeStyle = secondary
    ctx.lineWidth = 2.5
    ctx.stroke()
    ctx.shadowBlur = 0

    // Primary-color fill circle
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fillStyle = primary + 'dd'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.5)'
    ctx.lineWidth = 1
    ctx.stroke()
    ctx.restore()

    // Jersey number
    ctx.fillStyle = '#fff'
    ctx.font = `bold 9px monospace`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(player.jersey_number), x, y)

    // Player name: "F. Lastname" format, max 10 chars
    const nameParts = player.name.trim().split(/\s+/)
    const lastName = nameParts.length > 1
      ? `${nameParts[0][0]}. ${nameParts.slice(1).join(' ')}`.slice(0, 11)
      : player.name.slice(0, 11)
    ctx.font = `bold 8px monospace`
    ctx.textBaseline = 'top'
    const nameW = ctx.measureText(lastName).width
    ctx.fillStyle = 'rgba(0,0,0,0.65)'
    ctx.fillRect(x - nameW / 2 - 2, y + r + 2, nameW + 4, 10)
    ctx.fillStyle = 'rgba(255,255,255,0.95)'
    ctx.fillText(lastName, x, y + r + 3)

    // Goal contributions (above circle)
    const contribs: string[] = []
    if (player.goals > 0) contribs.push(`⚽${player.goals}`)
    if (player.assists > 0) contribs.push(`👟${player.assists}`)
    if (contribs.length > 0) {
      ctx.font = `8px sans-serif`
      ctx.textBaseline = 'bottom'
      ctx.fillStyle = '#fbbf24'
      ctx.fillText(contribs.join(' '), x, y - r - 2)
    }
  }
  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
}

// ---- Event markers ----
function drawEvents(
  ctx: CanvasRenderingContext2D,
  markers: PitchMarker[],
  width: number,
  height: number,
  padding: number
) {
  const now = Date.now()
  for (const marker of markers) {
    const age = now - marker.timestamp
    if (age > MARKER_FADE_MS) continue
    const opacity = Math.max(0, 1 - age / MARKER_FADE_MS)
    const { x, y } = sbToCanvas(marker.position[0], marker.position[1], width, height, padding)
    const color = getMarkerColor(marker)

    // Pass — draw as simple dot only (chem trail handles the line)
    if (marker.event_type === 'Pass') {
      ctx.globalAlpha = opacity * 0.6
      ctx.beginPath()
      ctx.arc(x, y, 3, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
      ctx.globalAlpha = 1
      continue
    }

    // Shot trajectory
    if (marker.event_type === 'Shot' && marker.end_position) {
      const { x: ex, y: ey } = sbToCanvas(marker.end_position[0], marker.end_position[1], width, height, padding)
      ctx.globalAlpha = opacity * 0.6
      ctx.strokeStyle = color
      ctx.lineWidth = 1.5
      ctx.setLineDash([3, 2])
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(ex, ey); ctx.stroke()
      ctx.setLineDash([])
    }

    // Flash ring for critical
    if (marker.priority === 'critical' && age < FLASH_DURATION_MS) {
      const fOpacity = 1 - age / FLASH_DURATION_MS
      ctx.beginPath()
      ctx.arc(x, y, 7 + 10 * (1 - fOpacity), 0, Math.PI * 2)
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.globalAlpha = opacity * fOpacity * 0.9
      ctx.stroke()
    }

    // Dot
    const dotR = marker.priority === 'critical' ? 8 : marker.priority === 'notable' ? 6 : 4
    ctx.globalAlpha = opacity
    ctx.beginPath()
    ctx.arc(x, y, dotR, 0, Math.PI * 2)
    ctx.fillStyle = color
    ctx.fill()

    // Label for goals
    if (marker.event_type === 'Shot' && (marker.details as Record<string,string>)?.shot_outcome === 'Goal') {
      ctx.font = 'bold 11px sans-serif'
      ctx.fillStyle = '#fff'
      ctx.textAlign = 'center'
      ctx.fillText('GOAL', x, y - dotR - 4)
      ctx.textAlign = 'left'
    }
  }
  ctx.globalAlpha = 1.0
}

export const PitchCanvas: React.FC<PitchCanvasProps> = ({
  markers,
  ballHistory,
  matchSpeed,
  dangerEntries,
  homeTeam,
  awayTeam,
  overlays,
  lineup,
  heatmapData,
  heatmapTeam = 'home',
  heatmapGranularity = 4,
  shots,
  buildUpVectors,
  homeColorPrimary   = HOME_COLOR,
  homeColorSecondary = '#16a34a',
  awayColorPrimary   = AWAY_COLOR,
  awayColorSecondary = '#1d4ed8',
  className = '',
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animFrameRef = useRef<number>(0)
  const markersRef = useRef(markers)
  const ballHistoryRef = useRef(ballHistory)
  const matchSpeedRef = useRef(matchSpeed)
  const dangerRef = useRef(dangerEntries)
  const lineupRef = useRef(lineup)
  const heatmapRef = useRef(heatmapData)
  const overlaysRef = useRef(overlays)
  const homeTeamRef = useRef(homeTeam)
  const awayTeamRef = useRef(awayTeam)
  const heatmapTeamRef = useRef(heatmapTeam)
  const granularityRef = useRef(heatmapGranularity)
  const shotsRef = useRef(shots)
  const vectorsRef = useRef(buildUpVectors)
  const homePrimaryRef   = useRef(homeColorPrimary)
  const homeSecondaryRef = useRef(homeColorSecondary)
  const awayPrimaryRef   = useRef(awayColorPrimary)
  const awaySecondaryRef = useRef(awayColorSecondary)

  markersRef.current = markers
  ballHistoryRef.current = ballHistory
  matchSpeedRef.current = matchSpeed
  dangerRef.current = dangerEntries
  lineupRef.current = lineup
  heatmapRef.current = heatmapData
  overlaysRef.current = overlays
  homeTeamRef.current = homeTeam
  awayTeamRef.current = awayTeam
  heatmapTeamRef.current = heatmapTeam
  granularityRef.current = heatmapGranularity
  shotsRef.current = shots
  vectorsRef.current = buildUpVectors
  homePrimaryRef.current   = homeColorPrimary
  homeSecondaryRef.current = homeColorSecondary
  awayPrimaryRef.current   = awayColorPrimary
  awaySecondaryRef.current = awayColorSecondary

  const render = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const { width, height } = canvas

    ctx.clearRect(0, 0, width, height)
    drawPitch(ctx, width, height)

    const ov = overlaysRef.current

    // Draw overlays in order (bottom to top): heatmap, vectors, shots, formation, live
    if (ov.heatmap) {
      drawHeatmap(ctx, heatmapRef.current, width, height, PADDING, granularityRef.current)
    }
    if (ov.vectors) {
      drawBuildUpVectors(ctx, vectorsRef.current, homeTeamRef.current, width, height, PADDING)
    }
    if (ov.shotmap) {
      drawShotMap(ctx, shotsRef.current, homeTeamRef.current, width, height, PADDING)
    }
    if (ov.formation) {
      drawFormation(ctx, lineupRef.current, width, height, PADDING,
        homePrimaryRef.current, homeSecondaryRef.current,
        awayPrimaryRef.current, awaySecondaryRef.current)
    }
    if (ov.live) {
      drawBallHistory(ctx, ballHistoryRef.current, matchSpeedRef.current, homeTeamRef.current, width, height, PADDING)
      drawDangerEntries(ctx, dangerRef.current, homeTeamRef.current, width, height, PADDING)
      drawEvents(ctx, markersRef.current, width, height, PADDING)
    }

    animFrameRef.current = requestAnimationFrame(render)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ro = new ResizeObserver(() => {
      const parent = canvas.parentElement ?? canvas
      canvas.width = parent.clientWidth
      canvas.height = parent.clientHeight
    })
    const parent = canvas.parentElement
    if (parent) {
      ro.observe(parent)
      canvas.width = parent.clientWidth
      canvas.height = parent.clientHeight
    }
    animFrameRef.current = requestAnimationFrame(render)
    return () => { ro.disconnect(); cancelAnimationFrame(animFrameRef.current) }
  }, [render])

  return (
    <canvas
      ref={canvasRef}
      className={`w-full h-full ${className}`}
      style={{ display: 'block' }}
    />
  )
}
