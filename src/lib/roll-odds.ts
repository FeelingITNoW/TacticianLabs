import type { RollOddsRun } from '@/data/types'

/** "Level 8: Lillia ×3, Ahri ×2 (4 out)", plus what else is gone from the pool */
export function describeRollOdds(run: RollOddsRun): string {
  const units = run.units
    .map((unit) => `${unit.name} ×${unit.copies}${unit.copiesOut > 0 ? ` (${unit.copiesOut} out)` : ''}`)
    .join(', ')
  const tierOut = run.tierOut.map((tier) => `${tier.copies} ${tier.cost}-cost`).join(', ')
  return `Level ${run.level}: ${units}${tierOut ? `; also gone from the pool: ${tierOut}` : ''}`
}

/** Gold the copies cost, which is where the curve starts */
export function copiesCost(run: RollOddsRun): number {
  return run.curve[0]?.gold ?? 0
}

/**
 * One run per distinct calculation, in the order first asked. Two calls with the same level,
 * units and pool have the same curve, so their asked amounts are merged into one run.
 * (Curves differ only in length, as each runs to cover the gold its call asked about.)
 */
export function distinctRollOdds(runs: RollOddsRun[]): RollOddsRun[] {
  const seen = new Map<string, RollOddsRun>()
  for (const run of runs) {
    const key = JSON.stringify([run.level, run.units, run.tierOut])
    const first = seen.get(key)
    if (!first) {
      seen.set(key, run)
      continue
    }
    const results = new Map(first.results.map((row) => [row.gold, row]))
    for (const row of run.results) results.set(row.gold, row)
    // A call that asked for more gold has a longer curve, which holds the shorter one
    seen.set(key, {
      ...first,
      results: [...results.values()].sort((a, b) => a.gold - b.gold),
      curve: run.curve.length > first.curve.length ? run.curve : first.curve,
    })
  }
  return [...seen.values()]
}
