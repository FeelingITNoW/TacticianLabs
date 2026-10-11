import { Link, createFileRoute, notFound } from '@tanstack/react-router'
import { getCompFn } from '@/data/compositions.functions'
import type { CompTrait, CompUnit } from '@/data/types'
import { DataTable, type Column } from '@/components/data-table'
import { GameIcon } from '@/components/game-icon'
import { NotFoundState, PageHeader } from '@/components/page-states'
import { Placement } from '@/components/stat-cells'
import { categoryLabel } from '@/lib/comps'
import { compact, pct } from '@/lib/format'
import { useState } from 'react'

export const Route = createFileRoute('/compositions/$compId')({
  loader: async ({ params }) => {
    const comp = await getCompFn({ data: { compId: params.compId } })
    if (!comp) throw notFound()
    return comp
  },
  head: ({ loaderData }) => ({ meta: [{ title: `${loaderData?.label ?? 'Composition'} · TFT Data Analyzer` }] }),
  notFoundComponent: () => (
    <NotFoundState
      title="Composition not found"
      description="Comps are re-clustered as the patch goes on, so older links can stop working."
    />
  ),
  component: CompositionPage,
})

const unitColumns: Column<CompUnit>[] = [
  {
    id: 'unit',
    header: 'Unit',
    sortValue: (u) => u.name,
    cell: (u) => (
      <Link
        to="/units/$unitId"
        params={{ unitId: u.apiName }}
        search={{ tab: 'items' }}
        className="flex items-center gap-3 hover:underline"
      >
        <GameIcon kind="champion" image={u.image} name={u.name} cost={u.cost} size={36} />
        <span className="font-medium">{u.name}</span>
        {u.carry && <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-[10px] uppercase text-amber-300">Carry</span>}
      </Link>
    ),
  },
  { id: 'frequency', header: 'In comp', align: 'right', sortValue: (u) => u.frequency, cell: (u) => pct(u.frequency, 0) },
  { id: 'star', header: 'Avg ★', align: 'right', sortValue: (u) => u.avgStar, cell: (u) => u.avgStar.toFixed(1) },
  { id: 'items', header: 'Avg items', align: 'right', sortValue: (u) => u.avgItems, cell: (u) => u.avgItems.toFixed(1) },
]

const traitColumns: Column<CompTrait>[] = [
  {
    id: 'trait',
    header: 'Trait',
    sortValue: (t) => t.name,
    cell: (t) => (
      <span className="flex items-center gap-3">
        <GameIcon kind="trait" image={t.image} name={t.name} size={28} />
        <span className="font-medium">{t.name}</span>
      </span>
    ),
  },
  { id: 'frequency', header: 'In comp', align: 'right', sortValue: (t) => t.frequency, cell: (t) => pct(t.frequency, 0) },
  { id: 'tier', header: 'Avg tier', align: 'right', sortValue: (t) => t.avgTier, cell: (t) => t.avgTier.toFixed(1) },
]

function CompositionPage() {
  const comp = Route.useLoaderData()
  const [unitSort, setUnitSort] = useState<{ id: string; dir: 'asc' | 'desc' }>({ id: 'frequency', dir: 'desc' })
  const [traitSort, setTraitSort] = useState<{ id: string; dir: 'asc' | 'desc' }>({ id: 'frequency', dir: 'desc' })

  return (
    <>
      <p className="mb-4 text-sm">
        <Link to="/compositions" className="text-muted-foreground hover:text-foreground">
          ← All compositions
        </Link>
      </p>
      <PageHeader title={comp.label} description={`${categoryLabel(comp.category)} · ${compact(comp.games)} boards this patch`} />

      <dl className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          ['Avg place', <Placement key="p" value={comp.averagePlacement} />],
          ['Top 4', pct(comp.top4Rate)],
          ['Win', pct(comp.winRate)],
          ['Games', compact(comp.games)],
          ['Per game', comp.frequency.toFixed(2)],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-lg border bg-card p-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="grid gap-8 lg:grid-cols-[3fr_2fr]">
        <section>
          <h2 className="mb-3 text-lg font-semibold">Units</h2>
          <DataTable
            columns={unitColumns}
            rows={comp.units}
            rowKey={(u) => u.apiName}
            sort={unitSort}
            onSortChange={setUnitSort}
          />
        </section>
        <section>
          <h2 className="mb-3 text-lg font-semibold">Traits</h2>
          <DataTable
            columns={traitColumns}
            rows={comp.traits}
            rowKey={(t) => t.apiName}
            sort={traitSort}
            onSortChange={setTraitSort}
          />
        </section>
      </div>
    </>
  )
}
