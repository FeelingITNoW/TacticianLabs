import type { GoldProjectionRun, StreakScenarioName } from '@/data/types'

/** The three Streak Scenarios, in the order the tables and charts list them */
export const SCENARIOS: { key: StreakScenarioName; label: string }[] = [
  { key: 'win', label: 'Win streak' },
  { key: 'mixed', label: 'Mixed' },
  { key: 'loss', label: 'Loss streak' },
]

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

/** One run per distinct question, in the order first asked: the same call twice has the same chart */
export function distinctGoldProjections(runs: GoldProjectionRun[]): GoldProjectionRun[] {
  const seen = new Map<string, GoldProjectionRun>()
  for (const run of runs) {
    const key = JSON.stringify([run.endRound, run.start, run.augments])
    if (!seen.has(key)) seen.set(key, run)
  }
  return [...seen.values()]
}
