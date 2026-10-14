import { useMemo } from 'react'
import { Link, createFileRoute, stripSearchParams } from '@tanstack/react-router'
import { z } from 'zod'
import { getUnitsFn } from '@/data/units.functions'
import type { UnitRow } from '@/data/types'
import { DataTable, type Column } from '@/components/data-table'
import { FilterSelect } from '@/components/filter-select'
import { GameIcon } from '@/components/game-icon'
import { PageHeader } from '@/components/page-states'
import { Placement, Rate } from '@/components/stat-cells'
import { compact } from '@/lib/format'

const SORTS = ['unit', 'cost', 'placement', 'top4', 'win', 'games', 'frequency'] as const

const defaults = { minGames: 100, sort: 'placement', dir: 'asc' } as const

const searchSchema = z.object({
  cost: z.number().int().min(1).max(5).optional().catch(undefined),
  // Hides the one-off skins and unreleased units that only have a handful of boards
  minGames: z.number().int().min(0).default(defaults.minGames).catch(defaults.minGames),
  sort: z.enum(SORTS).default(defaults.sort).catch(defaults.sort),
  dir: z.enum(['asc', 'desc']).default(defaults.dir).catch(defaults.dir),
})

export const Route = createFileRoute('/units/')({
  validateSearch: searchSchema,
  search: { middlewares: [stripSearchParams(defaults)] },
  loader: () => getUnitsFn(),
  head: () => ({ meta: [{ title: 'Units · Tactician Labs' }] }),
  component: UnitsPage,
})

const columns: Column<UnitRow>[] = [
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
        <GameIcon kind="champion" image={u.image} name={u.name} cost={u.cost} size={40} />
        <span className="font-medium">{u.name}</span>
      </Link>
    ),
  },
  { id: 'cost', header: 'Cost', align: 'right', sortValue: (u) => u.cost, firstDir: 'asc', cell: (u) => u.cost },
  {
    id: 'placement',
    header: 'Avg place',
    align: 'right',
    sortValue: (u) => u.averagePlacement,
    firstDir: 'asc',
    cell: (u) => <Placement value={u.averagePlacement} />,
  },
  { id: 'top4', header: 'Top 4', align: 'right', sortValue: (u) => u.top4Rate, cell: (u) => <Rate value={u.top4Rate} /> },
  { id: 'win', header: 'Win', align: 'right', sortValue: (u) => u.winRate, cell: (u) => <Rate value={u.winRate} /> },
  { id: 'games', header: 'Games', align: 'right', sortValue: (u) => u.games, cell: (u) => compact(u.games) },
  {
    id: 'frequency',
    header: 'Per game',
    align: 'right',
    sortValue: (u) => u.frequency,
    cell: (u) => u.frequency.toFixed(2),
  },
]

const COSTS = ['all', '1', '2', '3', '4', '5'] as const
const MIN_GAMES = [0, 100, 1000, 10000]

function UnitsPage() {
  const units = Route.useLoaderData()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()

  const rows = useMemo(
    () => units.filter((u) => u.games >= search.minGames && (search.cost === undefined || u.cost === search.cost)),
    [units, search.minGames, search.cost],
  )

  return (
    <>
      <PageHeader
        title="Units"
        description="How each unit performs when it is on a board. Per game is how many boards in a typical game field the unit."
      >
        <div className="flex flex-wrap gap-4">
          <FilterSelect
            label="Cost"
            value={search.cost === undefined ? 'all' : (String(search.cost) as (typeof COSTS)[number])}
            options={COSTS.map((c) => ({ value: c, label: c === 'all' ? 'All' : `${c}-cost` }))}
            onChange={(c) =>
              navigate({ search: (prev) => ({ ...prev, cost: c === 'all' ? undefined : Number(c) }), replace: true })
            }
          />
          <FilterSelect
            label="Min games"
            value={String(search.minGames)}
            options={MIN_GAMES.map((n) => ({ value: String(n), label: n === 0 ? 'Any' : compact(n) }))}
            onChange={(n) => navigate({ search: (prev) => ({ ...prev, minGames: Number(n) }), replace: true })}
          />
        </div>
      </PageHeader>
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(u) => u.apiName}
        sort={{ id: search.sort, dir: search.dir }}
        onSortChange={(s) =>
          navigate({ search: (prev) => ({ ...prev, sort: s.id as (typeof SORTS)[number], dir: s.dir }), replace: true })
        }
        empty="No units match these filters."
      />
    </>
  )
}
