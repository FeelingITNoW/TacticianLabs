import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { RollOddsRun } from '@/data/types'
import { pct } from '@/lib/format'
import { copiesCost, describeRollOdds } from '@/lib/roll-odds'

const HEIGHT = 240
const MARGIN = { top: 12, right: 48, bottom: 40, left: 44 }
const Y_TICKS = [0, 0.25, 0.5, 0.75, 1]
// An asked amount gets a dot once its odds clear this, else it would sit on the 0% line
const MIN_DOT_ODDS = 0.01
// What a roll costs (ROLL_COST in ai_tools/roll_odds.py); the curve has a point per roll
const ROLL_COST = 2

/** Odds as a percentage, with a decimal more below 1% so a small chance doesn't read as 0 */
function odds(value: number): string {
  return value > 0 && value < 0.01 ? pct(value, 2) : pct(value)
}

/** Round x ticks that don't crowd a plot `width` px wide */
function xTicks(max: number, width: number): { ticks: number[]; top: number } {
  let step = max <= 150 ? 25 : 50
  while ((max / step + 1) * 40 > width) step *= 2
  const top = Math.ceil(max / step) * step
  return { ticks: Array.from({ length: top / step + 1 }, (_, i) => i * step), top }
}

/** The chance of hitting a board against the gold spent, with a readout of every unit on hover */
export function RollOddsChart({ run }: { run: RollOddsRun }) {
  const wrapper = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(640)
  const [active, setActive] = useState<number | null>(null)

  useEffect(() => {
    const element = wrapper.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const { curve, results } = run
  const spend = copiesCost(run)
  const plotWidth = width - MARGIN.left - MARGIN.right
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const reach = Math.max(curve[curve.length - 1]?.gold ?? 0, ...results.map((row) => row.gold))
  const { ticks, top: xMax } = xTicks(reach, plotWidth)
  const x = (gold: number) => MARGIN.left + (gold / xMax) * plotWidth
  const y = (value: number) => MARGIN.top + (1 - value) * plotHeight
  const baseline = y(0)

  // Nothing is hit before the copies are paid for, so the line runs along 0% until then
  const points = [[x(0), baseline], ...curve.map((p) => [x(p.gold), y(p.allUnits)])]
  const line = points.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`).join('')
  const area = `${line}L${points[points.length - 1][0].toFixed(1)},${baseline}L${x(0)},${baseline}Z`

  const end = curve[curve.length - 1]
  const shown = active === null ? null : curve[active]
  const summary =
    `${describeRollOdds(run)}. Chance of hitting every unit: ` +
    results.map((row) => `${odds(row.allUnits)} at ${row.gold} gold`).join(', ') +
    (end ? `; ${odds(end.allUnits)} at ${end.gold} gold.` : '.')

  const at = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const gold = ((event.clientX - box.left) / box.width) * xMax
    setActive(Math.min(curve.length - 1, Math.max(0, Math.round((gold - spend) / ROLL_COST))))
  }
  const onKeyDown = (event: KeyboardEvent) => {
    const move = { ArrowLeft: -1, ArrowRight: 1 }[event.key]
    if (move === undefined) return
    event.preventDefault()
    setActive((i) => Math.min(curve.length - 1, Math.max(0, (i ?? curve.length - 1) + move)))
  }

  return (
    <figure className="space-y-1">
      <figcaption>
        <p className="text-sm font-medium">{describeRollOdds(run)}</p>
        <p className="text-xs text-muted-foreground">
          The first {spend} gold buys the copies, then {ROLL_COST} gold a roll
        </p>
      </figcaption>
      <div
        ref={wrapper}
        className="relative rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
        tabIndex={0}
        onKeyDown={onKeyDown}
        onFocus={() => setActive((i) => i ?? curve.length - 1)}
        onBlur={() => setActive(null)}
      >
        <svg width={width} height={HEIGHT} role="img" aria-label={summary} className="block">
          {Y_TICKS.map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={MARGIN.left + plotWidth} y1={y(tick)} y2={y(tick)} className="stroke-border" />
              <text x={MARGIN.left - 8} y={y(tick) + 4} textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">
                {pct(tick, 0)}
              </text>
            </g>
          ))}
          {ticks.map((tick) => (
            <text key={tick} x={x(tick)} y={baseline + 18} textAnchor="middle" className="fill-muted-foreground text-[11px] tabular-nums">
              {tick}
            </text>
          ))}
          <text x={MARGIN.left + plotWidth / 2} y={HEIGHT - 6} textAnchor="middle" className="fill-muted-foreground text-[11px]">
            Gold spent
          </text>
          <text
            transform={`translate(12 ${MARGIN.top + plotHeight / 2}) rotate(-90)`}
            textAnchor="middle"
            className="fill-muted-foreground text-[11px]"
          >
            Chance to hit
          </text>

          <path d={area} className="fill-primary/10" />
          <path d={line} fill="none" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className="stroke-primary" />

          {shown && <line x1={x(shown.gold)} x2={x(shown.gold)} y1={MARGIN.top} y2={baseline} className="stroke-muted-foreground" />}
          {results
            .filter((row) => row.allUnits >= MIN_DOT_ODDS)
            .map((row) => (
            <circle key={row.gold} cx={x(row.gold)} cy={y(row.allUnits)} r={4} strokeWidth={2} className="fill-primary stroke-card" />
            ))}
          {shown && <circle cx={x(shown.gold)} cy={y(shown.allUnits)} r={5} strokeWidth={2} className="fill-primary stroke-card" />}
          {end && (
            <text x={x(end.gold) + 8} y={y(end.allUnits) + 4} className="fill-foreground text-[11px] font-medium tabular-nums">
              {odds(end.allUnits)}
            </text>
          )}

          <rect
            x={MARGIN.left}
            y={MARGIN.top}
            width={plotWidth}
            height={plotHeight}
            fill="transparent"
            style={{ touchAction: 'pan-y' }}
            onPointerMove={at}
            onPointerDown={at}
            onPointerLeave={() => setActive(null)}
          />
        </svg>
        {shown && (
          <div
            className="pointer-events-none absolute z-10 min-w-36 rounded-md border bg-card p-2 text-xs shadow-sm"
            style={{
              top: MARGIN.top,
              ...(x(shown.gold) > width / 2 ? { right: width - x(shown.gold) + 10 } : { left: x(shown.gold) + 10 }),
            }}
          >
            <p className="text-sm font-semibold tabular-nums">{odds(shown.allUnits)}</p>
            <p className="text-muted-foreground">
              at {shown.gold} gold, {shown.rolls} {shown.rolls === 1 ? 'roll' : 'rolls'}
            </p>
            {run.units.length > 1 && (
              <ul className="mt-1 space-y-0.5 border-t pt-1">
                {run.units.map((unit) => (
                  <li key={unit.name} className="flex justify-between gap-4">
                    <span className="text-muted-foreground">{unit.name}</span>
                    <span className="tabular-nums">{odds(shown.perUnit[unit.name] ?? 0)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </figure>
  )
}
