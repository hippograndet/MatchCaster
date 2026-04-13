// frontend/src/components/PitchCanvas.tsx
// Animated pitch: event markers, chem-trail passes, formation overlay, heatmap

import React, { useRef, useEffect, useCallback } from 'react'
import { drawPitch, sbToCanvas } from '../utils/pitchCoords'
import type { PitchMarker, PitchOverlays, HeatmapTeam, LineupPlayer, ShotData, BuildUpZone } from '../utils/types'

export interface PassTrailPoint {
  from: [number, number]
  to: [number, number]
  team: string
  timestamp: number
}

export interface DangerEntry {
  position: [number, number]
  team: string
  timestamp: number
}

interface PitchCanvasProps {
  markers: PitchMarker[]
  passTrail: PassTrailPoint[]
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
  className?: string
}

const MARKER_FADE_MS = 8000
const FLASH_DURATION_MS = 700
const TRAIL_FADE_MS = 12000   // chem trail fades over 12 seconds
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

// ---- Chem trail ----
function drawPassTrail(
  ctx: CanvasRenderingContext2D,
  trail: PassTrailPoint[],
  homeTeam: string,
  width: number,
  height: number,
  padding: number
) {
  if (trail.length === 0) return
  const now = Date.now()

  for (let i = 0; i < trail.length; i++) {
    const pt = trail[i]
    const age = now - pt.timestamp
    if (age > TRAIL_FADE_MS) continue
    const opacity = Math.pow(1 - age / TRAIL_FADE_MS, 1.5)  // non-linear fade, newer = more vivid

    const { x: x1, y: y1 } = sbToCanvas(pt.from[0], pt.from[1], width, height, padding)
    const { x: x2, y: y2 } = sbToCanvas(pt.to[0], pt.to[1], width, height, padding)

    const isHome = pt.team === homeTeam
    const baseColor = isHome ? '34,197,94' : '59,130,246'  // green or blue RGB

    // Draw line with glow effect
    ctx.save()
    ctx.globalAlpha = opacity * 0.8
    ctx.strokeStyle = `rgba(${baseColor},1)`
    ctx.lineWidth = 1.5 + opacity * 1.5
    ctx.shadowColor = `rgba(${baseColor},${opacity})`
    ctx.shadowBlur = 4 + opacity * 6
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(x1, y1)
    ctx.lineTo(x2, y2)
    ctx.stroke()

    // Arrow tip on most recent passes
    if (opacity > 0.5) {
      const angle = Math.atan2(y2 - y1, x2 - x1)
      const al = 6 * opacity
      ctx.fillStyle = `rgba(${baseColor},${opacity})`
      ctx.globalAlpha = opacity
      ctx.shadowBlur = 0
      ctx.beginPath()
      ctx.moveTo(x2, y2)
      ctx.lineTo(x2 - al * Math.cos(angle - Math.PI / 6), y2 - al * Math.sin(angle - Math.PI / 6))
      ctx.lineTo(x2 - al * Math.cos(angle + Math.PI / 6), y2 - al * Math.sin(angle + Math.PI / 6))
      ctx.closePath()
      ctx.fill()
    }
    ctx.restore()
  }
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
  padding: number
) {
  for (const player of lineup) {
    const [sbX, sbY] = getFormationCoords(player.position, player.team)
    const { x, y } = sbToCanvas(sbX, sbY, width, height, padding)
    const color = player.team === 'home' ? HOME_COLOR : AWAY_COLOR
    const r = 13

    // Glow ring
    ctx.save()
    ctx.shadowColor = color
    ctx.shadowBlur = 8
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fillStyle = color + 'cc'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.75)'
    ctx.lineWidth = 1.5
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
  passTrail,
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
  className = '',
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animFrameRef = useRef<number>(0)
  const markersRef = useRef(markers)
  const trailRef = useRef(passTrail)
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

  markersRef.current = markers
  trailRef.current = passTrail
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
      drawFormation(ctx, lineupRef.current, width, height, PADDING)
    }
    if (ov.live) {
      drawPassTrail(ctx, trailRef.current, homeTeamRef.current, width, height, PADDING)
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
