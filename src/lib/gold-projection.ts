import type { GoldProjectionPoint, GoldProjectionRun, GoldProjectionScenario } from '@/data/types'

/**
 * What each Scenario is drawn in, by its position in the call, so a scenario keeps its colour
 * however many there are; their Free Rolls are a lighter step of it, so they read as part of
 * the same gold
 */
export const SCENARIO_STYLES = [
  { fill: 'fill-series-1', swatch: 'bg-series-1', rollFill: 'fill-series-1/40', rollSwatch: 'bg-series-1/40' },
  { fill: 'fill-series-2', swatch: 'bg-series-2', rollFill: 'fill-series-2/40', rollSwatch: 'bg-series-2/40' },
  { fill: 'fill-series-3', swatch: 'bg-series-3', rollFill: 'fill-series-3/40', rollSwatch: 'bg-series-3/40' },
]

/** What a Free Roll is worth: what a roll costs (ROLL_COST in ai_tools/roll_odds.py) */
export const ROLL_COST = 2

/** What a round is, short enough to sit under its bar; PvP rounds need no mark */
export const ROUND_MARK: Record<GoldProjectionPoint['kind'], string> = { pvp: '', carousel: 'Car', neutral: 'Neu' }

/** A gold amount as shown, with the one decimal the mixed scenario's averages can have */
export function amount(value: number): string {
  return String(Math.round(value * 10) / 10)
}

/** The levels a projection prices (LEVEL_TARGETS in ai_tools/gold_projection.py) */
export const LEVEL_TARGETS = ['8', '9']

/** "To 4-2 from 2-1 at level 4, with Pot of Gold at 2-1": what the projection was asked */
export function describeGoldProjection(run: GoldProjectionRun): string {
  const { start } = run
  const from = `from ${start.round} at level ${start.level}${start.gold > 0 ? ` with ${start.gold} gold` : ''}`
  const augments = run.augments.map((a) => `${a.name} at ${a.slot}`).join(', ')
  return `To ${run.endRound} ${from}${augments ? `, with ${augments}` : ''}`
}

/** A leftover as the page shows it: a shortfall says so instead of showing a minus sign */
export function leftoverText(leftover: number): string {
  return leftover < 0 ? `short ${-leftover}` : String(leftover)
}

/** What a Scenario did in a round, as text: gold gained, spent on units and spent on XP */
export function movesText(point: GoldProjectionPoint): string {
  const moves = [
    point.gained > 0 && `+${amount(point.gained)} gained`,
    point.spent > 0 && `-${amount(point.spent)} units`,
    point.leveling > 0 && `-${amount(point.leveling)} XP`,
  ].filter(Boolean)
  return moves.length > 0 ? moves.join(', ') : '-'
}

/** Whether every Scenario has the same XP in every round, so one XP chart serves them all */
export function sameXp(scenarios: GoldProjectionScenario[]): boolean {
  const xp = (s: GoldProjectionScenario) => JSON.stringify(s.series.map((p) => [p.naturalXp, p.augmentXp, p.boughtXp]))
  return scenarios.every((s) => xp(s) === xp(scenarios[0]))
}

/** One run per distinct question, in the order first asked: the same call twice has the same chart */
export function distinctGoldProjections(runs: GoldProjectionRun[]): GoldProjectionRun[] {
  const seen = new Map<string, GoldProjectionRun>()
  for (const run of runs) {
    const scenarios = run.scenarios.map((s) => [s.label, s.fights, s.series.map((p) => [p.gold, p.boughtXp])])
    const key = JSON.stringify([run.endRound, run.start, run.augments, scenarios])
    if (!seen.has(key)) seen.set(key, run)
  }
  return [...seen.values()]
}
