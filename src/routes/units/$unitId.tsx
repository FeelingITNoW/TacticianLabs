import { useMemo } from 'react'
import { Await, Link, createFileRoute, notFound, stripSearchParams } from '@tanstack/react-router'
import { z } from 'zod'
import { getItemizationFn, getTriosFn } from '@/data/units.functions'
import type { ItemRef, Stats, UnitRow } from '@/data/types'
import { DataTable, type Column } from '@/components/data-table'
import { FilterSelect } from '@/components/filter-select'
import { GameIcon } from '@/components/game-icon'
import { NotFoundState, PageHeader } from '@/components/page-states'
import { Placement, PlacementDelta, Rate } from '@/components/stat-cells'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { compact, pct } from '@/lib/format'
import { ITEM_TYPE_LABELS } from '@/lib/items'

const TABS = ['items', 'duos', 'trios'] as const
const SORTS = ['items', 'placement', 'top4', 'win', 'games', 'share'] as const
const MIN_GAMES = [0, 10, 25, 100, 500]

const defaults = { tab: 'items', minGames: 25, components: false, sort: 'placement', dir: 'asc' } as const

const searchSchema = z.object({
  tab: z.enum(TABS).default(defaults.tab).catch(defaults.tab),
  minGames: z.number().int().min(0).default(defaults.minGames).catch(defaults.minGames),
  // Components are only a step towards a completed item, so they are hidden unless asked for
  components: z.boolean().default(defaults.components).catch(defaults.components),
  sort: z.enum(SORTS).default(defaults.sort).catch(defaults.sort),
  dir: z.enum(['asc', 'desc']).default(defaults.dir).catch(defaults.dir),
})

export const Route = createFileRoute('/units/$unitId')({
  validateSearch: searchSchema,
  search: { middlewares: [stripSearchParams(defaults)] },
  // The 1 GB trios query only starts when its tab is open
  loaderDeps: ({ search }) => ({ wantsTrios: search.tab === 'trios' }),
  loader: async ({ params, deps }) => {
    const itemization = await getItemizationFn({ data: { unitId: params.unitId } })
    if (!itemization) throw notFound()
    const trios = deps.wantsTrios ? getTriosFn({ data: { unitId: params.unitId } }) : null
    return { itemization, trios }
  },
  head: ({ loaderData }) => ({
    meta: [{ title: `${loaderData?.itemization.unit.name ?? 'Unit'} · Tactician Labs` }],
  }),
  notFoundComponent: () => (
    <NotFoundState
      title="Unit not found"
      description="There is no unit with that id in the current patch."
      backTo="/units"
      backLabel="Back to units"
    />
  ),
  component: UnitPage,
})

type Search = z.infer<typeof searchSchema>

function ItemChips({ items }: { items: readonly ItemRef[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {items.map((item, index) => (
        // Two copies of one item are a legitimate duo, so the id alone isn't a unique key
        <span key={`${item.apiName}:${index}`} className="flex items-center gap-2">
          <GameIcon kind="item" image={item.image} name={item.name} size={28} />
          <span className="text-sm">{item.name}</span>
          {item.itemType && item.itemType !== 'completed' && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
              {ITEM_TYPE_LABELS[item.itemType]}
            </span>
          )}
        </span>
      ))}
    </div>
  )
}

interface BuildRow extends Stats {
  items: readonly ItemRef[]
  share: number
}

function buildColumns(unit: UnitRow, what: string): Column<BuildRow>[] {
  return [
    {
      id: 'items',
      header: what,
      sortValue: (r) => r.items.map((i) => i.name).join(' + '),
      cell: (r) => <ItemChips items={r.items} />,
    },
    {
      id: 'placement',
      header: 'Avg place',
      align: 'right',
      sortValue: (r) => r.averagePlacement,
      firstDir: 'asc',
      cell: (r) => <Placement value={r.averagePlacement} baseline={unit.averagePlacement} />,
    },
    {
      id: 'delta',
      header: <span title="Average placement compared with this unit's own average">vs unit</span>,
      align: 'right',
      cell: (r) => <PlacementDelta value={r.averagePlacement} reference={unit.averagePlacement} />,
    },
    { id: 'top4', header: 'Top 4', align: 'right', sortValue: (r) => r.top4Rate, cell: (r) => <Rate value={r.top4Rate} /> },
    { id: 'win', header: 'Win', align: 'right', sortValue: (r) => r.winRate, cell: (r) => <Rate value={r.winRate} /> },
    { id: 'games', header: 'Games', align: 'right', sortValue: (r) => r.games, cell: (r) => compact(r.games) },
    {
      id: 'share',
      header: <span title="Share of this unit's boards that held it">Held</span>,
      align: 'right',
      sortValue: (r) => r.share,
      cell: (r) => pct(r.share),
    },
  ]
}

function UnitPage() {
  const { itemization, trios } = Route.useLoaderData()
  const { unit, items, duos } = itemization
  const search = Route.useSearch()
  const navigate = Route.useNavigate()

  const update = (patch: Partial<Search>) => navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
  const sort = { id: search.sort, dir: search.dir }

  const visible = <T extends BuildRow>(rows: T[]) =>
    rows.filter(
      (r) =>
        r.games >= search.minGames && (search.components || r.items.every((i) => i.itemType !== 'component')),
    )

  const itemRows = useMemo(
    () => visible(items.map((r) => ({ ...r, items: [r.item] as const }))),
    [items, search.minGames, search.components],
  )
  const duoRows = useMemo(() => visible(duos), [duos, search.minGames, search.components])

  const columns = useMemo(
    () => ({
      items: buildColumns(unit, 'Item'),
      duos: buildColumns(unit, 'Duo'),
      trios: buildColumns(unit, 'Trio'),
    }),
    [unit],
  )

  const table = (rows: BuildRow[], kind: keyof typeof columns, empty: string) => (
    <DataTable
      columns={columns[kind]}
      rows={rows}
      rowKey={(r) => r.items.map((i) => i.apiName).join('|')}
      sort={sort}
      onSortChange={(s) => update({ sort: s.id as Search['sort'], dir: s.dir })}
      empty={empty}
    />
  )

  return (
    <>
      <p className="mb-4 text-sm">
        <Link to="/units" className="text-muted-foreground hover:text-foreground">
          ← All units
        </Link>
      </p>
      <PageHeader title={unit.name} description={`${unit.cost}-cost unit · patch stats from ranked high-elo games`}>
        <GameIcon kind="champion" image={unit.image} name={unit.name} cost={unit.cost} size={72} />
      </PageHeader>

      <dl className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          ['Avg place', <Placement key="p" value={unit.averagePlacement} />],
          ['Top 4', pct(unit.top4Rate)],
          ['Win', pct(unit.winRate)],
          ['Games', compact(unit.games)],
          ['Per game', unit.frequency.toFixed(2)],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-lg border bg-card p-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <section aria-labelledby="itemization">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <h2 id="itemization" className="text-xl font-semibold tracking-tight">
            Itemization
          </h2>
          <div className="flex flex-wrap items-center gap-4">
            <FilterSelect
              label="Min games"
              value={String(search.minGames)}
              options={MIN_GAMES.map((n) => ({ value: String(n), label: n === 0 ? 'Any' : String(n) }))}
              onChange={(n) => update({ minGames: Number(n) })}
            />
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={search.components}
                onChange={(e) => update({ components: e.target.checked })}
              />
              Show components
            </label>
          </div>
        </div>

        <Tabs value={search.tab} onValueChange={(tab) => update({ tab: tab as Search['tab'] })}>
          <TabsList>
            <TabsTrigger value="items">Best items</TabsTrigger>
            <TabsTrigger value="duos">Item duos</TabsTrigger>
            <TabsTrigger value="trios">Item trios</TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="mt-4">
          {search.tab === 'items' && table(itemRows, 'items', 'No items with enough games.')}
          {search.tab === 'duos' && table(duoRows, 'duos', 'No item pairs with enough games.')}
          {search.tab === 'trios' &&
            (trios ? (
              <Await promise={trios} fallback={<TriosSkeleton />}>
                {(result) =>
                  'error' in result ? (
                    <p className="rounded-lg border border-destructive/40 p-6 text-sm text-muted-foreground">
                      {result.error}
                    </p>
                  ) : (
                    table(visible(result.rows), 'trios', 'No full builds with enough games.')
                  )
                }
              </Await>
            ) : (
              <TriosSkeleton />
            ))}
        </div>
        {search.tab === 'trios' && (
          <p className="mt-3 text-xs text-muted-foreground">
            Trios are counted from individual games when first opened, which can take a few seconds. Only units
            holding exactly three items count.
          </p>
        )}
      </section>
    </>
  )
}

function TriosSkeleton() {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Counting item trios">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}
