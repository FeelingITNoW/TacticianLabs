import { cn } from '@/lib/utils'
import { pct, placement, placementDelta } from '@/lib/format'

// Where a typical board finishes: 8 players, so 4.5 is the middle
export const BASELINE_PLACEMENT = 4.5

/** Colour for an average placement, relative to `baseline` (lower is better). */
export function placementTone(value: number, baseline = BASELINE_PLACEMENT): string {
  const delta = value - baseline
  if (delta <= -0.5) return 'text-emerald-400'
  if (delta <= -0.15) return 'text-lime-400'
  if (delta < 0.15) return 'text-zinc-200'
  if (delta < 0.5) return 'text-amber-400'
  return 'text-rose-400'
}

export function Placement({ value, baseline }: { value: number; baseline?: number }) {
  return <span className={cn('font-medium', placementTone(value, baseline))}>{placement(value)}</span>
}

/** Change in average placement against a reference (e.g. the unit's own average). */
export function PlacementDelta({ value, reference }: { value: number; reference: number }) {
  const delta = value - reference
  return (
    <span className={cn('text-xs', placementTone(reference + delta, reference))}>{placementDelta(delta)}</span>
  )
}

export function Rate({ value, digits = 1 }: { value: number; digits?: number }) {
  return <span>{pct(value, digits)}</span>
}
