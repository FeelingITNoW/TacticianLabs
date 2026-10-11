import { useMemo } from 'react'
import { createFileRoute, stripSearchParams } from '@tanstack/react-router'
import { z } from 'zod'
import { getItemStatsFn } from '@/data/items.functions'
import type { ItemStatRow } from '@/data/types'
import { DataTable, type Column } from '@/components/data-table'
import { FilterSelect } from '@/components/filter-select'
import { GameIcon } from '@/components/game-icon'
import { PageHeader } from '@/components/page-states'
import { Placement, Rate } from '@/components/stat-cells'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { compact } from '@/lib/format'
import { ITEM_TAB_IDS, ITEM_TABS, tabForItemType } from '@/lib/items'

const SORTS = ['item', 'placement', 'top4', 'win', 'games', 'frequency'] as const
const MIN_GAMES = [0, 25, 100, 1000]

const defaults = { tab: 'completed', minGames: 25, sort: 'placement', dir: 'asc' } as const

const searchSchema = z.object({
  tab: z.enum(ITEM_TAB_IDS).default(defaults.tab).catch(defaults.tab),
  minGames: z.number().int().min(0).default(defaults.minGames).catch(defaults.minGames),
  sort: z.enum(SORTS).default(defaults.sort).catch(defaults.sort),
  dir: z.enum(['asc', 'desc']).default(defaults.dir).catch(defaults.dir),
})

export const Route = createFileRoute('/items')({
  validateSearch: searchSchema,
  search: { middlewares: [stripSearchParams(defaults)] },
  loader: () => getItemStatsFn(),
  head: () => ({ meta: [{ title: 'Items · TFT Data Analyzer' }] }),
  component: ItemsPage,
})

const columns: Column<ItemStatRow>[] = [
  {
    id: 'item',
    header: 'Item',
    sortValue: (i) => i.name,
    cell: (i) => (
      <span className="flex items-center gap-3">
        <GameIcon kind="item" image={i.image} name={i.name} size={36} />
        <span className="font-medium">{i.name}</span>
      </span>
    ),
  },
  {
    id: 'placement',
    header: 'Avg place',
    align: 'right',
    sortValue: (i) => i.averagePlacement,
    firstDir: 'asc',
    cell: (i) => <Placement value={i.averagePlacement} />,
  },
  { id: 'top4', header: 'Top 4', align: 'right', sortValue: (i) => i.top4Rate, cell: (i) => <Rate value={i.top4Rate} /> },
  { id: 'win', header: 'Win', align: 'right', sortValue: (i) => i.winRate, cell: (i) => <Rate value={i.winRate} /> },
  { id: 'games', header: 'Games', align: 'right', sortValue: (i) => i.games, cell: (i) => compact(i.games) },
  {
    id: 'frequency',
    header: 'Per game',
    align: 'right',
    sortValue: (i) => i.frequency,
    cell: (i) => i.frequency.toFixed(2),
  },
]

const DESCRIPTIONS: Record<(typeof ITEM_TABS)[number]['id'], string> = {
  completed: 'The standard completed items.',
  artifacts: 'One-of-a-kind artifacts.',
  radiant: 'Radiant versions of completed items.',
  emblems: 'Trait emblems.',
  misc: 'Boosters, potions, consumables, chests and other items that are not gear.',
}

function ItemsPage() {
  const items = Route.useLoaderData()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()

  const rows = useMemo(
    () => items.filter((i) => tabForItemType(i.itemType) === search.tab && i.games >= search.minGames),
    [items, search.tab, search.minGames],
  )

  return (
    <>
      <PageHeader title="Items" description={`${DESCRIPTIONS[search.tab]} Stats are for boards that held the item.`}>
        <FilterSelect
          label="Min games"
          value={String(search.minGames)}
          options={MIN_GAMES.map((n) => ({ value: String(n), label: n === 0 ? 'Any' : compact(n) }))}
          onChange={(n) => navigate({ search: (prev) => ({ ...prev, minGames: Number(n) }), replace: true })}
        />
      </PageHeader>

      <Tabs
        value={search.tab}
        onValueChange={(tab) => navigate({ search: (prev) => ({ ...prev, tab: tab as typeof search.tab }), replace: true })}
        className="mb-4"
      >
        <TabsList>
          {ITEM_TABS.map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(i) => i.apiName}
        sort={{ id: search.sort, dir: search.dir }}
        onSortChange={(s) =>
          navigate({ search: (prev) => ({ ...prev, sort: s.id as (typeof SORTS)[number], dir: s.dir }), replace: true })
        }
        empty="No items with enough games in this category."
      />
    </>
  )
}
