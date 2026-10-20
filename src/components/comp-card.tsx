import { Link } from '@tanstack/react-router'
import type { CompRow } from '@/data/types'
import { GameIcon } from '@/components/game-icon'
import { Placement, Rate } from '@/components/stat-cells'
import { categoryLabel } from '@/lib/comps'
import { compact } from '@/lib/format'

// Traits are listed by how much of the comp they are: how often, and how high a tier
const TRAITS_SHOWN = 5

export function CompCard({ comp }: { comp: CompRow }) {
  const traits = [...comp.traits].sort((a, b) => b.frequency * b.avgTier - a.frequency * a.avgTier).slice(0, TRAITS_SHOWN)

  return (
    <Link
      to="/compositions/$compId"
      params={{ compId: comp.compId }}
      className="block rounded-lg border bg-card p-4 transition-colors hover:border-foreground/30"
    >
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">{comp.label}</h2>
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
              {categoryLabel(comp.category)}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {comp.units.map((unit) => (
              <span key={unit.apiName} className="relative" title={`${unit.name} · ${Math.round(unit.frequency * 100)}% of boards`}>
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
          <Stat label="Avg place" value={<Placement value={comp.averagePlacement} />} />
          <Stat label="Top 4" value={<Rate value={comp.top4Rate} />} />
          <Stat label="Win" value={<Rate value={comp.winRate} />} />
          <Stat label="Games" value={compact(comp.games)} />
        </dl>
      </div>
    </Link>
  )
}

export function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  )
}
