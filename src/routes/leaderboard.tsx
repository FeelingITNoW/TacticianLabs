import { useEffect, useState } from 'react'
import { createFileRoute, stripSearchParams } from '@tanstack/react-router'
import { Flame } from 'lucide-react'
import { z } from 'zod'
import { getLeaderboardFn } from '@/data/leaderboard.functions'
import type { LeaderboardRow, Tier } from '@/data/types'
import { DataTable, type Column } from '@/components/data-table'
import { FilterSelect } from '@/components/filter-select'
import { PageHeader } from '@/components/page-states'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { integer, pct, timeAgo } from '@/lib/format'
import { cn } from '@/lib/utils'

const TIERS = ['all', 'CHALLENGER', 'GRANDMASTER', 'MASTER'] as const

const defaults = { region: 'all', tier: 'all', q: '', page: 1 } as const

const searchSchema = z.object({
  region: z.string().max(10).default(defaults.region).catch(defaults.region),
  tier: z.enum(TIERS).default(defaults.tier).catch(defaults.tier),
  // A hand-typed ?q=123 arrives as a number, so accept the scalar types and make a string of it
  q: z
    .union([z.string(), z.number(), z.boolean()])
    .transform(String)
    .pipe(z.string().max(60))
    .default(defaults.q).catch(defaults.q),
  page: z.number().int().min(1).default(defaults.page).catch(defaults.page),
})

export const Route = createFileRoute('/leaderboard')({
  validateSearch: searchSchema,
  search: { middlewares: [stripSearchParams(defaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ deps }) =>
    getLeaderboardFn({
      data: {
        region: deps.region === 'all' ? undefined : deps.region,
        tier: deps.tier === 'all' ? undefined : (deps.tier as Tier),
        q: deps.q || undefined,
        page: deps.page,
      },
    }),
  head: () => ({ meta: [{ title: 'Leaderboard · TFT Data Analyzer' }] }),
  component: LeaderboardPage,
})

const TIER_STYLE: Record<Tier, string> = {
  CHALLENGER: 'text-amber-300',
  GRANDMASTER: 'text-rose-400',
  MASTER: 'text-fuchsia-300',
}

const TIER_LABEL: Record<Tier, string> = { CHALLENGER: 'Challenger', GRANDMASTER: 'Grandmaster', MASTER: 'Master' }

const columns: Column<LeaderboardRow>[] = [
  { id: 'rank', header: '#', cell: (p) => <span className="text-muted-foreground">{integer(p.rank)}</span> },
  {
    id: 'player',
    header: 'Player',
    cell: (p) =>
      p.gameName ? (
        <span>
          <span className="font-medium">{p.gameName}</span>
          <span className="text-muted-foreground">#{p.tagLine}</span>
        </span>
      ) : (
        // Names only come from matches we have ingested
        <span className="text-muted-foreground italic">Unknown player</span>
      ),
  },
  { id: 'region', header: 'Region', cell: (p) => <span className="text-muted-foreground">{p.region}</span> },
  {
    id: 'tier',
    header: 'Tier',
    cell: (p) => <span className={cn('text-sm', TIER_STYLE[p.tier])}>{TIER_LABEL[p.tier]}</span>,
  },
  { id: 'lp', header: 'LP', align: 'right', cell: (p) => <span className="font-medium">{integer(p.leaguePoints)}</span> },
  {
    id: 'top4',
    header: <span title="Share of ranked games finished in the top 4">Top 4</span>,
    align: 'right',
    cell: (p) => (p.games > 0 ? pct(p.top4 / p.games) : '–'),
  },
  { id: 'games', header: 'Games', align: 'right', cell: (p) => integer(p.games) },
  {
    id: 'streak',
    header: '',
    cell: (p) => (p.hotStreak ? <Flame size={14} className="text-orange-400" aria-label="Hot streak" /> : null),
  },
]

function LeaderboardPage() {
  const data = Route.useLoaderData()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()

  // The box types freely; the URL (and so the query) follows 300 ms after the last key
  const [text, setText] = useState(search.q)
  useEffect(() => setText(search.q), [search.q])
  useEffect(() => {
    if (text === search.q) return
    const id = setTimeout(
      () => navigate({ search: (prev) => ({ ...prev, q: text, page: 1 }), replace: true }),
      300,
    )
    return () => clearTimeout(id)
  }, [text, search.q, navigate])

  const pages = Math.max(1, Math.ceil(data.total / data.pageSize))
  const go = (page: number) => navigate({ search: (prev) => ({ ...prev, page }) })
  const shown = data.regions.find((r) => r.region === search.region)
  const refreshed = shown?.refreshedAt ?? Math.min(...data.regions.map((r) => r.refreshedAt), Date.now())

  return (
    <>
      <PageHeader
        title="Leaderboard"
        description={`The Challenger, Grandmaster and Master ladder. Updated ${timeAgo(refreshed)}. Players show as unknown until they appear in an analysed match.`}
      >
        <div className="flex flex-wrap items-center gap-4">
          <FilterSelect
            label="Region"
            value={search.region}
            options={[
              { value: 'all', label: 'All regions' },
              ...data.regions.map((r) => ({ value: r.region, label: `${r.region} (${integer(r.players)})` })),
            ]}
            onChange={(region) => navigate({ search: (prev) => ({ ...prev, region, page: 1 }), replace: true })}
          />
          <FilterSelect
            label="Tier"
            value={search.tier}
            options={TIERS.map((t) => ({ value: t, label: t === 'all' ? 'All tiers' : TIER_LABEL[t] }))}
            onChange={(tier) => navigate({ search: (prev) => ({ ...prev, tier, page: 1 }), replace: true })}
          />
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search name#tag"
            aria-label="Search players"
            className="w-48"
          />
        </div>
      </PageHeader>

      <DataTable
        columns={columns}
        rows={data.rows}
        rowKey={(p) => `${p.region}:${p.rank}:${p.gameName ?? ''}:${p.leaguePoints}`}
        sort={{ id: 'rank', dir: 'asc' }}
        onSortChange={() => {}}
        empty="No players match these filters."
      />

      <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {integer(data.total)} players · page {search.page} of {pages}
        </span>
        <span className="flex gap-2">
          <Button variant="outline" size="sm" disabled={search.page <= 1} onClick={() => go(search.page - 1)}>
            Previous
          </Button>
          <Button variant="outline" size="sm" disabled={search.page >= pages} onClick={() => go(search.page + 1)}>
            Next
          </Button>
        </span>
      </div>
    </>
  )
}
