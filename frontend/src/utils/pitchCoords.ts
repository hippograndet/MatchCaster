// frontend/src/utils/pitchCoords.ts
// Map StatsBomb coordinates (120×80) to canvas pixel coordinates + draw pitch.

const SB_WIDTH  = 120
const SB_HEIGHT = 80

export interface CanvasCoords { x: number; y: number }

/**
 * Convert StatsBomb (x, y) to canvas pixel (cx, cy).
 * Canvas origin is top-left; StatsBomb origin is bottom-left, x=0→120 left→right.
 */
export function sbToCanvas(
  sbX: number, sbY: number,
  canvasWidth: number, canvasHeight: number,
  padding = 24,
): CanvasCoords {
  const usableW = canvasWidth  - padding * 2
  const usableH = canvasHeight - padding * 2
  const cx = padding + (sbX / SB_WIDTH)  * usableW
  const cy = padding + (1 - sbY / SB_HEIGHT) * usableH   // flip Y
  return { x: cx, y: cy }
}

/**
 * Draw a football pitch on the given canvas context.
 * Follows FIFA / StatsBomb coordinate conventions.
 */
export function drawPitch(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  padding = 24,
): void {
  const W = width  - padding * 2
  const H = height - padding * 2
  const p = padding

  // ── Grass ──────────────────────────────────────────────────────────────
  ctx.fillStyle = '#2a7a3f'
  ctx.fillRect(p, p, W, H)

  // Subtle alternating vertical stripes
  const stripeCount = 10
  const stripeW = W / stripeCount
  ctx.fillStyle = 'rgba(0,0,0,0.06)'
  for (let i = 0; i < stripeCount; i += 2) {
    ctx.fillRect(p + i * stripeW, p, stripeW, H)
  }

  // ── Lines ──────────────────────────────────────────────────────────────
  ctx.save()
  ctx.strokeStyle = 'rgba(255,255,255,0.88)'
  ctx.lineWidth = 1.5
  ctx.lineJoin = 'round'

  const scaleX = W / SB_WIDTH
  const scaleY = H / SB_HEIGHT

  function sb(x: number, y: number): CanvasCoords {
    return sbToCanvas(x, y, width, height, padding)
  }

  // Outer boundary
  ctx.strokeRect(p, p, W, H)

  // Centre line
  ctx.beginPath()
  ctx.moveTo(p + W / 2, p)
  ctx.lineTo(p + W / 2, p + H)
  ctx.stroke()

  // Centre circle (r = 10 SB units)
  const circleR = 10 * Math.min(scaleX, scaleY)
  ctx.beginPath()
  ctx.arc(p + W / 2, p + H / 2, circleR, 0, Math.PI * 2)
  ctx.stroke()

  // Centre spot
  ctx.fillStyle = 'rgba(255,255,255,0.88)'
  ctx.beginPath()
  ctx.arc(p + W / 2, p + H / 2, 2.5, 0, Math.PI * 2)
  ctx.fill()

  // ── Penalty areas (StatsBomb: x=0-18 left, x=102-120 right; y=18-62) ──
  // Left penalty area
  const pa = { x0: 0, x1: 18, y0: 18, y1: 62 }
  const leftPA  = sb(pa.x0, pa.y1)
  const leftPAw = 18 * scaleX
  const paH     = (pa.y1 - pa.y0) * scaleY
  ctx.strokeRect(leftPA.x, leftPA.y, leftPAw, paH)

  // Right penalty area (mirror)
  const rightPAx = sb(102, pa.y1).x
  ctx.strokeRect(rightPAx, leftPA.y, leftPAw, paH)

  // ── 6-yard boxes (x=0-6 left, x=114-120 right; y=30-50) ──
  const gb = { x0: 0, x1: 6, y0: 30, y1: 50 }
  const leftGB  = sb(gb.x0, gb.y1)
  const leftGBw = 6 * scaleX
  const gbH     = (gb.y1 - gb.y0) * scaleY
  ctx.strokeRect(leftGB.x, leftGB.y, leftGBw, gbH)

  const rightGBx = sb(114, gb.y1).x
  ctx.strokeRect(rightGBx, leftGB.y, leftGBw, gbH)

  // ── Goals (small rectangles extending outside boundary) ──
  // Goal width ≈ 8 SB units (y: 36–44)
  const goalW = 2.5 * scaleX   // depth of goal (into canvas off-pitch)
  const goalTop    = sb(0, 44).y
  const goalBottom = sb(0, 36).y
  const goalH = goalBottom - goalTop

  ctx.lineWidth = 1.8
  // Left goal
  ctx.strokeRect(p - goalW, goalTop, goalW, goalH)
  // Right goal
  ctx.strokeRect(p + W, goalTop, goalW, goalH)
  ctx.lineWidth = 1.5

  // ── Penalty spots ──
  const leftSpot  = sb(12, 40)
  const rightSpot = sb(108, 40)
  ctx.fillStyle = 'rgba(255,255,255,0.88)'
  for (const spot of [leftSpot, rightSpot]) {
    ctx.beginPath()
    ctx.arc(spot.x, spot.y, 2.5, 0, Math.PI * 2)
    ctx.fill()
  }

  // ── Penalty D arcs (arc outside penalty area) ──
  // distance from spot to penalty area edge = 6 SB units; arc radius = 10 SB units
  const dAngle = Math.acos(6 / 10)   // ≈ 0.9273 rad
  ctx.beginPath()
  ctx.arc(leftSpot.x, leftSpot.y, circleR, -dAngle, dAngle)
  ctx.stroke()
  ctx.beginPath()
  ctx.arc(rightSpot.x, rightSpot.y, circleR, Math.PI - dAngle, Math.PI + dAngle)
  ctx.stroke()

  // ── Corner arcs (r ≈ 1 yard = ~1 SB unit) ──
  const cornerR = 1 * Math.min(scaleX, scaleY) * 3   // slightly larger for visibility
  const corners: [number, number, number, number][] = [
    [p,     p,     0,             Math.PI / 2],
    [p + W, p,     Math.PI / 2,  Math.PI],
    [p + W, p + H, Math.PI,      1.5 * Math.PI],
    [p,     p + H, 1.5 * Math.PI, 2 * Math.PI],
  ]
  for (const [cx, cy, start, end] of corners) {
    ctx.beginPath()
    ctx.arc(cx, cy, cornerR, start, end)
    ctx.stroke()
  }

  ctx.restore()
}
