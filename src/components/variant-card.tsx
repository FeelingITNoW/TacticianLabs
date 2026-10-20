import { Link } from '@tanstack/react-router'
import type { VariantRow } from '@/data/types'
import { GameIcon } from '@/components/game-icon'
import { Stat } from '@/components/comp-card'
import { Placement, Rate } from '@/components/stat-cells'
import { compact, pct } from '@/lib/format'
import { cn } from '@/lib/utils'

const TRAITS_SHOWN = 5

/** A comp variant: its own board and stats, plus what it adds to or drops from the comp. */
export function VariantCard({ variant }: { variant: VariantRow }) {
  const traits = [...variant.traits].sort((a, b) => b.frequency * b.avgTier - a.frequency * a.avgTier).slice(0, TRAITS_SHOWN)

  return (
    <div className="my-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted-foreground">
            Variant of{' '}
            <Link to="/compositions/$compId" params={{ compId: variant.compId }} className="underline underline-offset-2">
              {variant.compLabel}
            </Link>{' '}
            · {pct(variant.shareOfComp, 0)} of its boards
          </p>
          <h2 className="mt-1 font-semibold">{variant.label}</h2>
          {variant.diff.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {variant.diff.map((d) => (
                <span
                  key={`${d.kind}:${d.apiName}`}
                  className={cn(
                    'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs',
                    d.change === 'added' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300',
                  )}
                >
                  {d.change === 'added' ? '+' : '−'}
                  {d.name}
                </span>
              ))}
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {variant.units.map((unit) => (
              <span key={unit.apiName} title={`${unit.name} · ${Math.round(unit.frequency * 100)}% of boards`}>
                <GameIcon
                  kind="champion"
                  image={unit.image}
                  name={unit.name}
                  cost={unit.cost}
                  size={unit.carry ? 44 : 36}
                  className={unit.carry ? 'outline outline-2 outline-offset-2 outline-amber-400' : undefined}
                />
              </span>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-3">
            {traits.map((trait) => (
              <span key={trait.apiName} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <GameIcon kind="trait" image={trait.image} name={trait.name} style={trait.style} size={22} />
                {trait.name} {Math.round(trait.avgTier)}
              </span>
            ))}
          </div>
        </div>
        <dl className="grid grid-cols-4 gap-x-5 text-right text-sm tabular-nums">
          <Stat label="Avg place" value={<Placement value={variant.averagePlacement} />} />
          <Stat label="Top 4" value={<Rate value={variant.top4Rate} />} />
          <Stat label="Win" value={<Rate value={variant.winRate} />} />
          <Stat label="Games" value={compact(variant.games)} />
        </dl>
      </div>
    </div>
  )
}
