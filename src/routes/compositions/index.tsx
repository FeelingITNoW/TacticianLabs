import { useMemo } from 'react'
import { createFileRoute, stripSearchParams } from '@tanstack/react-router'
import { z } from 'zod'
import { getCompsFn } from '@/data/compositions.functions'
import { CompCard } from '@/components/comp-card'
import { FilterSelect } from '@/components/filter-select'
import { EmptyState, PageHeader } from '@/components/page-states'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CATEGORY_IDS, CATEGORY_LABELS } from '@/lib/comps'

const SORTS = ['placement', 'top4', 'win', 'games'] as const

const defaults = { sort: 'placement' } as const

const searchSchema = z.object({
  category: z.enum(CATEGORY_IDS).optional().catch(undefined),
  sort: z.enum(SORTS).default(defaults.sort).catch(defaults.sort),
})

export const Route = createFileRoute('/compositions/')({
  validateSearch: searchSchema,
  search: { middlewares: [stripSearchParams(defaults)] },
  loader: () => getCompsFn(),
  head: () => ({ meta: [{ title: 'Compositions · Tactician Labs' }] }),
  component: CompositionsPage,
})

const SORT_LABELS: Record<(typeof SORTS)[number], string> = {
  placement: 'Avg place',
  top4: 'Top 4 rate',
  win: 'Win rate',
  games: 'Most played',
}

function CompositionsPage() {
  const comps = Route.useLoaderData()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()

  const rows = useMemo(() => {
    const filtered = comps.filter((c) => search.category === undefined || c.category === search.category)
    const order = {
      placement: (a: (typeof comps)[number], b: (typeof comps)[number]) => a.averagePlacement - b.averagePlacement,
      top4: (a: (typeof comps)[number], b: (typeof comps)[number]) => b.top4Rate - a.top4Rate,
      win: (a: (typeof comps)[number], b: (typeof comps)[number]) => b.winRate - a.winRate,
      games: (a: (typeof comps)[number], b: (typeof comps)[number]) => b.games - a.games,
    }[search.sort]
    return [...filtered].sort(order)
  }, [comps, search.category, search.sort])

  // Categories that have no comps this patch aren't offered
  const present = useMemo(() => new Set(comps.map((c) => c.category)), [comps])

  return (
    <>
      <PageHeader
        title="Compositions"
        description="Boards grouped into comps by the units and traits they play. Stats are for boards that matched the comp; gold rings mark the carries."
      >
        <FilterSelect
          label="Sort by"
          value={search.sort}
          options={SORTS.map((s) => ({ value: s, label: SORT_LABELS[s] }))}
          onChange={(sort) => navigate({ search: (prev) => ({ ...prev, sort }), replace: true })}
        />
      </PageHeader>

      <Tabs
        value={search.category ?? 'all'}
        onValueChange={(value) =>
          navigate({
            search: (prev) => ({ ...prev, category: value === 'all' ? undefined : (value as typeof search.category) }),
            replace: true,
          })
        }
        className="mb-4"
      >
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="all">All</TabsTrigger>
          {CATEGORY_IDS.filter((id) => present.has(id)).map((id) => (
            <TabsTrigger key={id} value={id}>
              {CATEGORY_LABELS[id]}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {rows.length === 0 ? (
        <EmptyState
          title="No compositions yet"
          description="Comps appear once a patch has enough boards to cluster."
        />
      ) : (
        <div className="space-y-3">
          {rows.map((comp) => (
            <CompCard key={comp.compId} comp={comp} />
          ))}
        </div>
      )}
    </>
  )
}
