import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import type { GoldProjectionCurveLevel, GoldProjectionPoint, GoldProjectionRun, GoldProjectionScenario } from '@/data/types'
import {
  amount,
  describeGoldProjection,
  LEVEL_TARGETS,
  leftoverText,
  movesText,
  ROLL_COST,
  ROUND_MARK,
  SCENARIO_STYLES,
  sameXp,
} from '@/lib/gold-projection'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

// A round's slot is wide enough for its total and its name; narrower screens scroll sideways
const MIN_SLOT = 34
const MAX_BAR = 24
const BAR_RADIUS = 4
const MARGIN = { top: 24, bottom: 42, side: 8, thresholds: 48 }
// Threshold labels closer together than this would overlap
const MIN_LABEL_GAP = 13

interface Bar {
  round: string
  /** A short mark under the round: what kind of round it is, or the level reached */
  mark: string
  /** Stacked from the baseline; the total on the cap is the sum of the solid ones. An outlined segment is gold that was there and is gone */
  segments: { value: number; fill: string; outline?: boolean; label?: string }[]
  /** The tooltip's rows */
  details: { label: string; value: string }[]
}

interface Threshold {
  label: string
  value: number
  strong: boolean
}

/** A column with a rounded data end and a square foot on the baseline */
function column(x: number, top: number, width: number, bottom: number, rounded: boolean): string {
  const r = rounded ? Math.min(BAR_RADIUS, width / 2, bottom - top) : 0
  return `M${x},${bottom}V${top + r}Q${x},${top} ${x + r},${top}H${x + width - r}Q${x + width},${top} ${x + width},${top + r}V${bottom}Z`
}

/** One column per round, each with its total on the cap, and a breakdown on hover, touch and the arrow keys */
function RoundBars({
  title,
  note,
  height,
  yMax,
  bars,
  thresholds = [],
}: {
  title: string
  note?: ReactNode
  height: number
  yMax: number
  bars: Bar[]
  thresholds?: Threshold[]
}) {
  const wrapper = useRef<HTMLDivElement>(null)
  const [available, setAvailable] = useState(720)
  const [active, setActive] = useState<number | null>(null)

  useEffect(() => {
    const element = wrapper.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setAvailable(entry.contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const last = bars.length - 1
  const right = thresholds.length > 0 ? MARGIN.thresholds : MARGIN.side
  const width = Math.max(available, MARGIN.side + right + bars.length * MIN_SLOT)
  const plotWidth = width - MARGIN.side - right
  const slot = plotWidth / bars.length
  const barWidth = Math.min(MAX_BAR, Math.round(slot * 0.7))
  const baseline = height - MARGIN.bottom
  const plotHeight = baseline - MARGIN.top
  const y = (value: number) => baseline - (value / Math.max(yMax, 1)) * plotHeight
  const left = (i: number) => MARGIN.side + i * slot + (slot - barWidth) / 2
  const centre = (i: number) => MARGIN.side + (i + 0.5) * slot
  const total = (bar: Bar) => bar.segments.reduce((sum, segment) => sum + (segment.outline ? 0 : segment.value), 0)

  // Top down, so the targets at the top keep their labels if the low levels crowd each other
  const labelled: Threshold[] = []
  for (const threshold of [...thresholds].sort((a, b) => b.value - a.value)) {
    const previous = labelled[labelled.length - 1]
    if (!previous || y(threshold.value) - y(previous.value) >= MIN_LABEL_GAP) labelled.push(threshold)
  }

  const summary =
    `${title} by round. ` + bars.map((bar) => `${bar.round}: ${amount(total(bar))}`).join(', ') + '.'

  const at = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    setActive(Math.min(last, Math.max(0, Math.floor(((event.clientX - box.left) / box.width) * bars.length))))
  }
  const onKeyDown = (event: KeyboardEvent) => {
    const move = { ArrowLeft: -1, ArrowRight: 1 }[event.key]
    if (move === undefined) return
    event.preventDefault()
    setActive((i) => Math.min(last, Math.max(0, (i ?? last) + move)))
  }
  const shown = active === null ? null : bars[active]

  return (
    <figure className="min-w-0 space-y-1">
      <figcaption>
        <p className="text-sm font-medium">{title}</p>
        {note && <div className="text-xs text-muted-foreground">{note}</div>}
        {width > available && <p className="text-xs text-muted-foreground">Scroll sideways for every round.</p>}
      </figcaption>
      <div
        ref={wrapper}
        className="overflow-x-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
        tabIndex={0}
        onKeyDown={onKeyDown}
        onFocus={() => setActive((i) => i ?? last)}
        onBlur={() => setActive(null)}
      >
        <div className="relative" style={{ width, height }}>
          <svg width={width} height={height} role="img" aria-label={summary} className="block">
            {thresholds.map((threshold) => (
              <line
                key={threshold.label}
                x1={MARGIN.side}
                x2={MARGIN.side + plotWidth}
                y1={y(threshold.value)}
                y2={y(threshold.value)}
                className={threshold.strong ? 'stroke-muted-foreground' : 'stroke-border'}
              />
            ))}
            {labelled.map((threshold) => (
              <text
                key={threshold.label}
                x={MARGIN.side + plotWidth + 6}
                y={y(threshold.value) + 4}
                className={`text-[11px] ${threshold.strong ? 'fill-foreground font-medium' : 'fill-muted-foreground'}`}
              >
                {threshold.label}
              </text>
            ))}
            {bars.map((bar, i) =>
              bar.round.endsWith('-1') && i > 0 ? (
                <line
                  key={bar.round}
                  x1={MARGIN.side + i * slot}
                  x2={MARGIN.side + i * slot}
                  y1={MARGIN.top}
                  y2={height - 4}
                  className="stroke-border"
                />
              ) : null,
            )}
            <line x1={MARGIN.side} x2={MARGIN.side + plotWidth} y1={baseline} y2={baseline} className="stroke-muted-foreground" />

            {active !== null && <rect x={MARGIN.side + active * slot} y={MARGIN.top} width={slot} height={plotHeight} className="fill-muted" />}
            {bars.map((bar, i) => {
              const filled = bar.segments.filter((segment) => segment.value > 0)
              let reached = 0
              return (
                <g key={bar.round}>
                  {filled.map((segment, s) => {
                    const bottom = y(reached) - (s > 0 ? 2 : 0)
                    reached += segment.value
                    const isTop = s === filled.length - 1
                    const top = Math.min(y(reached), bottom - 1)
                    return (
                      <g key={s}>
                        <path
                          d={column(left(i), top, barWidth, bottom, isTop)}
                          className={segment.outline ? 'fill-none stroke-muted-foreground' : segment.fill}
                          strokeDasharray={segment.outline ? '3 2' : undefined}
                        />
                        {segment.outline && segment.label && bottom - top >= 14 && (
                          <text x={centre(i)} y={(top + bottom) / 2 + 3.5} textAnchor="middle" className="fill-muted-foreground text-[10px] tabular-nums">
                            {segment.label}
                          </text>
                        )}
                      </g>
                    )
                  })}
                  <text
                    x={centre(i)}
                    y={y(reached) - 6}
                    textAnchor="middle"
                    strokeWidth={3}
                    style={{ paintOrder: 'stroke' }}
                    className="fill-foreground stroke-background text-[11px] font-medium tabular-nums"
                  >
                    {amount(total(bar))}
                  </text>
                  <text x={centre(i)} y={baseline + 15} textAnchor="middle" className="fill-foreground text-[11px] tabular-nums">
                    {bar.round}
                  </text>
                  {bar.mark && (
                    <text x={centre(i)} y={baseline + 29} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                      {bar.mark}
                    </text>
                  )}
                </g>
              )
            })}

            <rect
              x={MARGIN.side}
              y={0}
              width={plotWidth}
              height={height}
              fill="transparent"
              style={{ touchAction: 'pan-x pan-y' }}
              onPointerMove={at}
              onPointerDown={at}
              onPointerLeave={() => setActive(null)}
            />
          </svg>
          {shown && active !== null && (
            <div
              className="pointer-events-none absolute z-10 min-w-40 rounded-md border bg-card p-2 text-xs shadow-sm"
              style={{
                top: MARGIN.top,
                ...(centre(active) > width / 2 ? { right: width - centre(active) + slot / 2 + 6 } : { left: centre(active) + slot / 2 + 6 }),
              }}
            >
              <p className="font-semibold tabular-nums">{shown.round}</p>
              <ul className="mt-1 space-y-0.5 border-t pt-1">
                {shown.details.map((row) => (
                  <li key={row.label} className="flex justify-between gap-4">
                    <span className="text-muted-foreground">{row.label}</span>
                    <span className="tabular-nums">{row.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </figure>
  )
}

function LegendKey({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`size-2.5 rounded-sm ${swatch}`} aria-hidden />
      {label}
    </span>
  )
}

function goldBars(series: GoldProjectionPoint[], fill: string, rollFill: string): Bar[] {
  return series.map((point, i) => {
    const { interest, passive, reward, carousel, augment } = point.income
    const bought = point.boughtXp - (series[i - 1]?.boughtXp ?? 0)
    return {
      round: point.round,
      mark: ROUND_MARK[point.kind],
      segments: [
        { value: point.gold, fill },
        { value: point.freeRollGold, fill: rollFill },
        { value: point.spent + point.leveling, fill: '', outline: true, label: `\u2212${amount(point.spent + point.leveling)}` },
      ],
      details: [
        { label: 'Held after buying', value: amount(point.totalGold) },
        ...(point.freeRolls > 0
          ? [
              { label: 'Gold', value: amount(point.gold) },
              { label: `${point.freeRolls} Free Rolls`, value: amount(point.freeRollGold) },
            ]
          : []),
        { label: 'Income this round', value: `+${amount(interest + passive + reward + carousel + augment)}` },
        ...(point.kind === 'carousel'
          ? [{ label: 'Carousel unit', value: amount(carousel) }]
          : [
              { label: 'Interest', value: amount(interest) },
              { label: 'Passive', value: amount(passive) },
              { label: "Last round's reward", value: amount(reward) },
            ]),
        ...(augment > 0 ? [{ label: 'Augment', value: amount(augment) }] : []),
        ...(point.gained > 0 ? [{ label: 'Gained', value: `+${amount(point.gained)}` }] : []),
        ...(point.spent > 0 ? [{ label: 'Spent on units', value: `-${amount(point.spent)}` }] : []),
        ...(point.leveling > 0
          ? [{ label: 'Spent on XP', value: `-${amount(point.leveling)} (+${bought} XP)` }]
          : []),
      ],
    }
  })
}

function xpBars(series: GoldProjectionPoint[], curve: GoldProjectionCurveLevel[], boughtFill: string): Bar[] {
  return series.map((point) => {
    const total = point.naturalXp + point.augmentXp + point.boughtXp
    const next = curve.find((row) => row.totalXp > total)
    return {
      round: point.round,
      mark: `Lv ${point.level}`,
      segments: [
        { value: point.naturalXp, fill: 'fill-muted-foreground' },
        { value: point.augmentXp, fill: 'fill-primary' },
        { value: point.boughtXp, fill: boughtFill },
      ],
      details: [
        { label: 'XP held', value: String(total) },
        { label: 'Natural', value: String(point.naturalXp) },
        ...(point.augmentXp > 0 ? [{ label: 'From augments', value: String(point.augmentXp) }] : []),
        ...(point.boughtXp > 0 ? [{ label: 'Bought', value: String(point.boughtXp) }] : []),
        { label: 'Level', value: String(point.level) },
        ...(next ? [{ label: `To level ${next.level}`, value: `${next.totalXp - total} XP` }] : []),
      ],
    }
  })
}

const earnedXp = (scenario: GoldProjectionScenario) => scenario.naturalXp + scenario.augmentXp + scenario.boughtXp

/** Every round's numbers as text, for reading across the scenarios and for screen readers */
function RoundsTable({ run }: { run: GoldProjectionRun }) {
  const { scenarios } = run
  const augmentXp = scenarios[0].augmentXp > 0
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted-foreground">Every round as a table</summary>
      <div className="mt-2 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Round</TableHead>
              {scenarios.flatMap((scenario) => [
                <TableHead key={`${scenario.label}-gold`} className="text-right">
                  {scenario.label}: held
                </TableHead>,
                <TableHead key={`${scenario.label}-moves`}>Moves</TableHead>,
                <TableHead key={`${scenario.label}-level`} className="text-right">
                  Level
                </TableHead>,
              ])}
              {augmentXp && <TableHead className="text-right">Augment XP</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {scenarios[0].series.map((point, i) => (
              <TableRow key={point.round}>
                <TableCell>
                  {point.round} {point.kind !== 'pvp' && <span className="text-muted-foreground">{point.kind}</span>}
                </TableCell>
                {scenarios.flatMap((scenario) => {
                  const at = scenario.series[i]
                  return [
                    <TableCell key={`${scenario.label}-gold`} className="text-right tabular-nums">
                      {at.gold}
                    </TableCell>,
                    <TableCell key={`${scenario.label}-moves`} className="text-muted-foreground">
                      {movesText(at)}
                    </TableCell>,
                    <TableCell key={`${scenario.label}-level`} className="text-right tabular-nums">
                      {at.level}
                    </TableCell>,
                  ]
                })}
                {augmentXp && <TableCell className="text-right tabular-nums">{point.augmentXp}</TableCell>}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </details>
  )
}

/** The XP-level table of each distinct curve: what is missing and costs depends on the XP the scenario bought */
function curveGroups(scenarios: GoldProjectionScenario[]) {
  const groups = new Map<string, { labels: string[]; curve: GoldProjectionCurveLevel[] }>()
  for (const scenario of scenarios) {
    const key = JSON.stringify(scenario.levelCurve)
    const group = groups.get(key) ?? { labels: [], curve: scenario.levelCurve }
    group.labels.push(scenario.label)
    groups.set(key, group)
  }
  return [...groups.values()]
}

/**
 * One gold_projection call: a bar chart of the gold held by round for each Scenario, on one
 * scale so they compare, with the Free Rolls stacked on as the gold they're worth, then the XP
 * (natural, from augments and bought) against every level's threshold, then what levels 8 and 9
 * cost against what is left and the whole XP curve.
 */
export function GoldProjectionCharts({ run }: { run: GoldProjectionRun }) {
  const { scenarios } = run
  const first = scenarios[0]
  const freeRolls = first.freeRolls
  const rollsFrom = first.series.find((point) => point.freeRolls > 0)?.round
  const allCeiling = scenarios.every((scenario) => scenario.ceiling)
  const anySpend = !allCeiling
  // The whole stack, so what was there before spending fits
  const goldMax = Math.max(
    ...scenarios.flatMap((scenario) => scenario.series.map((point) => point.totalGold + point.spent + point.leveling)),
  )
  const curve = first.levelCurve
  const xpMax = Math.max(...scenarios.map(earnedXp), curve[curve.length - 1]?.totalXp ?? 0)
  const shared = sameXp(scenarios)
  const xpTitle = `XP earned against the level curve, from level ${run.start.level}`
  const xpNote = (hasBought: boolean, swatch: string) => (
    <>
      <p>Each line is the XP a level takes; the level the XP reaches is under each round.</p>
      {(first.augmentXp > 0 || hasBought) && (
        <p className="mt-1 flex flex-wrap gap-x-4">
          <LegendKey swatch="bg-muted-foreground" label="Natural XP" />
          {first.augmentXp > 0 && <LegendKey swatch="bg-primary" label="From augments" />}
          {hasBought && <LegendKey swatch={swatch} label="Bought with gold" />}
        </p>
      )}
    </>
  )
  const thresholds = curve.map((row) => ({
    label: `Lv ${row.level}`,
    value: row.totalXp,
    strong: LEVEL_TARGETS.includes(String(row.level)),
  }))
  const groups = curveGroups(scenarios)

  return (
    <section className="space-y-5">
      <div>
        <p className="text-sm font-medium">{describeGoldProjection(run)}</p>
        <p className="text-xs text-muted-foreground">
          {allCeiling
            ? 'The bold number is the gold held after each round’s buying, before its fight. Nothing is spent on the way, so the gold is a ceiling, and win and loss streaks are the extremes, not forecasts.'
            : `The bold number is the gold each scenario holds after each round’s buying, before its fight; the dashed outline is what that round spent.${
                scenarios.some((scenario) => scenario.ceiling) ? ' A scenario that spends nothing is a ceiling.' : ''
              } Win and loss streaks are the extremes, not forecasts.`}{' '}
          Car is a carousel, Neu neutrals.
        </p>
        {freeRolls > 0 && (
          <p className="mt-1 text-xs font-medium">
            The gold includes {first.freeRollGold} gold of Free Rolls: {freeRolls} at {ROLL_COST} gold a roll, from {rollsFrom}.
            They roll like gold but can&rsquo;t buy XP.
          </p>
        )}
      </div>
      {scenarios.map((scenario, i) => {
        const style = SCENARIO_STYLES[i]
        return (
          <RoundBars
            key={i}
            title={`Gold held after buying: ${scenario.label}`}
            note={
              <>
                {scenario.fights && <p className="break-all font-mono">Fights: {scenario.fights}</p>}
                <p className="flex flex-wrap gap-x-4">
                  <LegendKey swatch={style.swatch} label="Held after buying" />
                  {freeRolls > 0 && <LegendKey swatch={style.rollSwatch} label={`Free Rolls, ${ROLL_COST} gold each`} />}
                  {scenario.spent + scenario.leveling > 0 && (
                    <LegendKey swatch="border border-dashed border-muted-foreground" label="Spent this round" />
                  )}
                </p>
              </>
            }
            height={260}
            yMax={goldMax}
            bars={goldBars(scenario.series, style.fill, style.rollFill)}
          />
        )
      })}
      {shared ? (
        <RoundBars
          title={xpTitle}
          note={xpNote(first.boughtXp > 0, 'bg-foreground/70')}
          height={420}
          yMax={xpMax}
          bars={xpBars(first.series, curve, 'fill-foreground/70')}
          thresholds={thresholds}
        />
      ) : (
        scenarios.map((scenario, i) => (
          <RoundBars
            key={i}
            title={`${xpTitle}: ${scenario.label}`}
            note={xpNote(scenario.boughtXp > 0, SCENARIO_STYLES[i].swatch)}
            height={420}
            yMax={xpMax}
            bars={xpBars(scenario.series, curve, SCENARIO_STYLES[i].fill)}
            thresholds={thresholds}
          />
        ))
      )}

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Scenario</TableHead>
              <TableHead className="text-right">Level</TableHead>
              <TableHead className="text-right">Held at {run.endRound}</TableHead>
              {anySpend && <TableHead className="text-right">Spent</TableHead>}
              {LEVEL_TARGETS.flatMap((level) => [
                <TableHead key={`${level}-cost`} className="text-right">
                  Level {level} cost
                </TableHead>,
                <TableHead key={`${level}-left`} className="text-right">
                  Left after {level}
                </TableHead>,
              ])}
            </TableRow>
          </TableHeader>
          <TableBody>
            {scenarios.map((scenario, i) => (
              <TableRow key={i}>
                <TableCell>
                  <LegendKey swatch={SCENARIO_STYLES[i].swatch} label={scenario.label} />
                </TableCell>
                <TableCell className="text-right tabular-nums">{scenario.level}</TableCell>
                <TableCell className="text-right font-medium tabular-nums">{scenario.totalGold}</TableCell>
                {anySpend && (
                  <TableCell className="text-right tabular-nums">{amount(scenario.spent + scenario.leveling)}</TableCell>
                )}
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
            ))}
          </TableBody>
        </Table>
      </div>

      {curve.length > 0 &&
        groups.map(({ labels, curve: rows }) => (
          <div key={labels.join()} className="space-y-1">
            {groups.length > 1 && <p className="text-xs font-medium">{labels.join(', ')}</p>}
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Level</TableHead>
                    <TableHead className="text-right">XP for the level</TableHead>
                    <TableHead className="text-right">XP from {run.start.round}</TableHead>
                    <TableHead className="text-right">Reached</TableHead>
                    <TableHead className="text-right">XP missing at {run.endRound}</TableHead>
                    <TableHead className="text-right">Gold to buy it</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.level} className={LEVEL_TARGETS.includes(String(row.level)) ? 'font-medium' : undefined}>
                      <TableCell>{row.level}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.xp}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.totalXp}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.reachedAt ?? `not by ${run.endRound}`}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.xpMissing}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.goldCost}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        ))}

      <p className="text-xs text-muted-foreground">
        The cost is the gold that buys the XP still missing at {run.endRound} in 4-gold purchases, from the XP each scenario
        holds then (natural, from augments and bought); level 9&rsquo;s cost already includes level 8&rsquo;s.
        {freeRolls > 0 &&
          ` What is left counts the ${first.freeRollGold} gold of Free Rolls, which can still roll; a shortfall is in gold alone, since they can't buy XP.`}{' '}
        Gold spent on board units is not taken off, except what a scenario&rsquo;s own spending enters.
      </p>
      <RoundsTable run={run} />
    </section>
  )
}
