import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { GoldProjectionRun } from '@/data/types'
import { describeGoldProjection, LEVEL_TARGETS, leftoverText, SCENARIOS } from '@/lib/gold-projection'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const HEIGHT = 200
const MARGIN = { top: 12, right: 12, bottom: 28, left: 40 }

interface Line {
  label: string
  /** Tailwind stroke and fill classes, so the line follows the theme */
  stroke: string
  fill: string
  /** SVG dash pattern, so the lines differ by more than colour */
  dash?: string
  values: number[]
}

/** A y axis top that is a round number, with ticks at every step up to it */
function yScale(max: number): { top: number; ticks: number[] } {
  const target = Math.max(max, 1)
  let step = 1
  while (target / step > 4) step *= target / step > 8 ? 5 : 2
  const top = Math.ceil(target / step) * step
  return { top, ticks: Array.from({ length: top / step + 1 }, (_, i) => i * step) }
}

/** The rounds that get a label on the x axis: each stage's first, and the last */
function xTickIndexes(rounds: string[]): number[] {
  const last = rounds.length - 1
  const stages = rounds.flatMap((round, i) => (round.endsWith('-1') && i < last - 2 ? [i] : []))
  return [...stages, last]
}

/** Lines by round, with a readout of every line on hover, touch and the arrow keys */
function ProjectionChart({ title, note, rounds, lines }: { title: string; note?: string; rounds: string[]; lines: Line[] }) {
  const wrapper = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(320)
  const [active, setActive] = useState<number | null>(null)

  useEffect(() => {
    const element = wrapper.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(220, entry.contentRect.width)))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const last = rounds.length - 1
  const plotWidth = width - MARGIN.left - MARGIN.right
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const { top, ticks } = yScale(Math.max(...lines.flatMap((line) => line.values)))
  const x = (i: number) => MARGIN.left + (i / last) * plotWidth
  const y = (value: number) => MARGIN.top + (1 - value / top) * plotHeight
  const path = (values: number[]) =>
    values.map((value, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(value).toFixed(1)}`).join('')

  const summary =
    `${title} by round, ${rounds[0]} to ${rounds[last]}. ` +
    lines.map((line) => `${line.label}: ${line.values[last]} at ${rounds[last]}`).join('; ') +
    '.'

  const at = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    setActive(Math.min(last, Math.max(0, Math.round(((event.clientX - box.left) / box.width) * last))))
  }
  const onKeyDown = (event: KeyboardEvent) => {
    const move = { ArrowLeft: -1, ArrowRight: 1 }[event.key]
    if (move === undefined) return
    event.preventDefault()
    setActive((i) => Math.min(last, Math.max(0, (i ?? last) + move)))
  }

  return (
    <figure className="min-w-0 space-y-1">
      <figcaption>
        <p className="text-sm font-medium">{title}</p>
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
      </figcaption>
      <div
        ref={wrapper}
        className="relative rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
        tabIndex={0}
        onKeyDown={onKeyDown}
        onFocus={() => setActive((i) => i ?? last)}
        onBlur={() => setActive(null)}
      >
        <svg width={width} height={HEIGHT} role="img" aria-label={summary} className="block">
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={MARGIN.left + plotWidth} y1={y(tick)} y2={y(tick)} className="stroke-border" />
              <text x={MARGIN.left - 6} y={y(tick) + 4} textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">
                {tick}
              </text>
            </g>
          ))}
          {xTickIndexes(rounds).map((i) => (
            <text key={i} x={x(i)} y={HEIGHT - 8} textAnchor="middle" className="fill-muted-foreground text-[11px] tabular-nums">
              {rounds[i]}
            </text>
          ))}

          {active !== null && (
            <line x1={x(active)} x2={x(active)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} className="stroke-muted-foreground" />
          )}
          {lines.map((line) => (
            <path
              key={line.label}
              d={path(line.values)}
              fill="none"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={line.dash}
              className={line.stroke}
            />
          ))}
          {active !== null &&
            lines.map((line) => (
              <circle key={line.label} cx={x(active)} cy={y(line.values[active])} r={4} strokeWidth={2} className={`${line.fill} stroke-card`} />
            ))}

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
        {active !== null && (
          <div
            className="pointer-events-none absolute z-10 min-w-32 rounded-md border bg-card p-2 text-xs shadow-sm"
            style={{
              top: MARGIN.top,
              ...(x(active) > width / 2 ? { right: width - x(active) + 10 } : { left: x(active) + 10 }),
            }}
          >
            <p className="font-semibold tabular-nums">{rounds[active]}</p>
            <ul className="mt-1 space-y-0.5 border-t pt-1">
              {lines.map((line) => (
                <li key={line.label} className="flex justify-between gap-4">
                  <span className="text-muted-foreground">{line.label}</span>
                  <span className="tabular-nums">{line.values[active]}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </figure>
  )
}

const SCENARIO_LINES = {
  win: { stroke: 'stroke-chart-1', fill: 'fill-chart-1', dash: undefined },
  mixed: { stroke: 'stroke-chart-2', fill: 'fill-chart-2', dash: '6 4' },
  loss: { stroke: 'stroke-chart-3', fill: 'fill-chart-3', dash: '2 3' },
}

/**
 * One gold_projection call: the gold by round for each Streak Scenario, the XP and Free Rolls
 * (the same in every scenario, since only gold depends on how the fights go), and what levels
 * 8 and 9 cost against what is left.
 */
export function GoldProjectionCharts({ run }: { run: GoldProjectionRun }) {
  const { win } = run.scenarios
  const rounds = win.series.map((point) => point.round)
  const hasAugmentXp = win.augmentXp > 0

  return (
    <section className="space-y-3">
      <div>
        <p className="text-sm font-medium">{describeGoldProjection(run)}</p>
        <p className="text-xs text-muted-foreground">
          What you can spend in {run.endRound}&rsquo;s planning phase, before its fight. Nothing is spent on the way, so the gold
          is a ceiling, and win and loss streaks are the extremes, not forecasts.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <ProjectionChart
          title="Gold"
          rounds={rounds}
          lines={SCENARIOS.map(({ key, label }) => ({
            label,
            ...SCENARIO_LINES[key],
            values: run.scenarios[key].series.map((point) => point.gold),
          }))}
        />
        <ProjectionChart
          title="XP earned"
          note={hasAugmentXp ? 'Natural XP and the augments' : 'Natural XP'}
          rounds={rounds}
          lines={[
            { label: 'Natural', stroke: 'stroke-chart-1', fill: 'fill-chart-1', values: win.series.map((p) => p.naturalXp) },
            ...(hasAugmentXp
              ? [
                  {
                    label: 'With augments',
                    stroke: 'stroke-chart-2',
                    fill: 'fill-chart-2',
                    dash: '6 4',
                    values: win.series.map((p) => p.naturalXp + p.augmentXp),
                  },
                ]
              : []),
          ]}
        />
        <ProjectionChart
          title="Free Rolls"
          note="Granted by augments"
          rounds={rounds}
          lines={[{ label: 'Free Rolls', stroke: 'stroke-chart-1', fill: 'fill-chart-1', values: win.series.map((p) => p.freeRolls) }]}
        />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden>
        {SCENARIOS.map(({ key, label }) => (
          <span key={key} className="flex items-center gap-1.5">
            <svg width="22" height="6">
              <line x1="0" x2="22" y1="3" y2="3" strokeWidth={2} strokeDasharray={SCENARIO_LINES[key].dash} className={SCENARIO_LINES[key].stroke} />
            </svg>
            {label}
          </span>
        ))}
      </div>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Streak</TableHead>
              <TableHead className="text-right">Gold</TableHead>
              {LEVEL_TARGETS.map((level) => (
                <TableHead key={level} colSpan={2} className="text-right">
                  Level {level}: cost, left over
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {SCENARIOS.map(({ key, label }) => {
              const scenario = run.scenarios[key]
              return (
                <TableRow key={key}>
                  <TableCell>{label}</TableCell>
                  <TableCell className="text-right font-medium tabular-nums">{scenario.gold}</TableCell>
                  {LEVEL_TARGETS.flatMap((level) => {
                    const row = scenario.levels[level]
                    return [
                      <TableCell key={`${level}-cost`} className="text-right tabular-nums">
                        {row.goldCost}
                      </TableCell>,
                      <TableCell
                        key={`${level}-left`}
                        className={`text-right tabular-nums ${row.leftover < 0 ? 'text-destructive' : 'font-medium'}`}
                      >
                        {leftoverText(row.leftover)}
                      </TableCell>,
                    ]
                  })}
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        The XP reaches level {win.level} on its own ({win.naturalXp + win.augmentXp} XP
        {hasAugmentXp ? `, ${win.augmentXp} from augments` : ''}); the cost is the gold that buys the rest, in
        4-gold purchases. Gold spent on board units is not taken off.
      </p>
    </section>
  )
}
