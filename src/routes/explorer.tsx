import { createFileRoute, stripSearchParams } from '@tanstack/react-router'
import { X } from 'lucide-react'
import { EMPTY_QUERY, explorerQuerySchema, isEmptyQuery, type ExplorerQuery } from '@/data/explorer'
import { getReferenceListsFn } from '@/data/meta.functions'
import type { Entity } from '@/data/types'
import { FilterSelect } from '@/components/filter-select'
import { GameIcon } from '@/components/game-icon'
import { PageHeader } from '@/components/page-states'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export const Route = createFileRoute('/explorer')({
  // The filters live in the URL, so a query can be shared once the backend exists
  validateSearch: explorerQuerySchema,
  search: { middlewares: [stripSearchParams(EMPTY_QUERY)] },
  loader: () => getReferenceListsFn(),
  head: () => ({ meta: [{ title: 'Explorer · Tactician Labs' }] }),
  component: ExplorerPage,
})

function AddPicker({
  placeholder,
  options,
  onAdd,
}: {
  placeholder: string
  options: Entity[]
  onAdd: (apiName: string) => void
}) {
  return (
    // value stays empty so the placeholder shows again after each pick
    <Select value="" onValueChange={onAdd}>
      <SelectTrigger size="sm" className="w-56" aria-label={placeholder}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="max-h-72">
        {options.map((o) => (
          <SelectItem key={o.apiName} value={o.apiName}>
            {o.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function Chip({ children, onRemove, label }: { children: React.ReactNode; onRemove: () => void; label: string }) {
  return (
    <span className="flex items-center gap-2 rounded-md border bg-card py-1 pr-1 pl-2 text-sm">
      {children}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${label}`}
        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <X size={14} />
      </button>
    </span>
  )
}

function Section({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border p-4">
      <h2 className="font-semibold">{title}</h2>
      <p className="mb-3 text-xs text-muted-foreground">{hint}</p>
      {children}
    </section>
  )
}

function ExplorerPage() {
  const reference = Route.useLoaderData()
  const query = Route.useSearch()
  const navigate = Route.useNavigate()

  const set = (patch: Partial<ExplorerQuery>) => navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
  const champion = (apiName: string) => reference.champions.find((c) => c.apiName === apiName)
  const trait = (apiName: string) => reference.traits.find((t) => t.apiName === apiName)
  const item = (apiName: string) => reference.items.find((i) => i.apiName === apiName)

  return (
    <>
      <PageHeader
        title="Data explorer"
        description="Filter boards by the units, traits and items they field, and see how they place."
      >
        <FilterSelect
          label="Show"
          value={query.groupBy}
          options={[
            { value: 'units', label: 'Units' },
            { value: 'items', label: 'Items' },
            { value: 'traits', label: 'Traits' },
          ]}
          onChange={(groupBy) => set({ groupBy })}
        />
      </PageHeader>

      <p className="mb-6 rounded-lg border border-amber-400/30 bg-amber-400/5 p-4 text-sm">
        <strong className="font-medium">Not available yet.</strong> The explorer needs a backend that counts
        arbitrary combinations from individual games, and that doesn't exist. You can build a filter here; it is saved
        in the page address and will run once the backend is added.
      </p>

      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Units" hint="Boards that field all of these">
          <div className="space-y-2">
            {query.units.map((u, index) => {
              const ref = champion(u.apiName)
              return (
                <div key={u.apiName} className="flex flex-wrap items-center gap-2">
                  <Chip label={ref?.name ?? u.apiName} onRemove={() => set({ units: query.units.filter((_, i) => i !== index) })}>
                    <GameIcon kind="champion" image={ref?.image ?? null} name={ref?.name ?? u.apiName} cost={ref?.cost} size={24} />
                    {ref?.name ?? u.apiName}
                  </Chip>
                  <FilterSelect
                    label="★"
                    value={String(u.minStar ?? 1)}
                    options={[1, 2, 3].map((s) => ({ value: String(s), label: `${s}+` }))}
                    onChange={(star) =>
                      set({ units: query.units.map((x, i) => (i === index ? { ...x, minStar: Number(star) } : x)) })
                    }
                  />
                </div>
              )
            })}
            <AddPicker
              placeholder="Add a unit…"
              options={reference.champions.filter((c) => !query.units.some((u) => u.apiName === c.apiName))}
              onAdd={(apiName) => set({ units: [...query.units, { apiName }] })}
            />
          </div>
        </Section>

        <Section title="Traits" hint="Boards with all of these active">
          <div className="space-y-2">
            {query.traits.map((t, index) => {
              const ref = trait(t.apiName)
              return (
                <div key={t.apiName} className="flex flex-wrap items-center gap-2">
                  <Chip label={ref?.name ?? t.apiName} onRemove={() => set({ traits: query.traits.filter((_, i) => i !== index) })}>
                    <GameIcon kind="trait" image={ref?.image ?? null} name={ref?.name ?? t.apiName} size={24} />
                    {ref?.name ?? t.apiName}
                  </Chip>
                  <FilterSelect
                    label="Tier"
                    value={String(t.minTier ?? 1)}
                    options={[1, 2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `${n}+` }))}
                    onChange={(tier) =>
                      set({ traits: query.traits.map((x, i) => (i === index ? { ...x, minTier: Number(tier) } : x)) })
                    }
                  />
                </div>
              )
            })}
            <AddPicker
              placeholder="Add a trait…"
              options={reference.traits.filter((t) => !query.traits.some((x) => x.apiName === t.apiName))}
              onAdd={(apiName) => set({ traits: [...query.traits, { apiName }] })}
            />
          </div>
        </Section>

        <Section title="Items" hint="Boards holding all of these items">
          <div className="space-y-2">
            {query.items.map((apiName) => {
              const ref = item(apiName)
              return (
                <div key={apiName}>
                  <Chip label={ref?.name ?? apiName} onRemove={() => set({ items: query.items.filter((x) => x !== apiName) })}>
                    <GameIcon kind="item" image={ref?.image ?? null} name={ref?.name ?? apiName} size={24} />
                    {ref?.name ?? apiName}
                  </Chip>
                </div>
              )
            })}
            <AddPicker
              placeholder="Add an item…"
              options={reference.items.filter((i) => i.itemType !== 'component' && !query.items.includes(i.apiName))}
              onAdd={(apiName) => set({ items: [...query.items, apiName] })}
            />
          </div>
        </Section>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button disabled title="The explorer backend isn't built yet">
          Run query
        </Button>
        {!isEmptyQuery(query) && (
          <Button variant="ghost" onClick={() => navigate({ search: { groupBy: query.groupBy, units: [], traits: [], items: [] } })}>
            Clear filters
          </Button>
        )}
      </div>

      <details className="mt-6 rounded-lg border p-4 text-sm">
        <summary className="cursor-pointer text-muted-foreground">Request the explorer would send</summary>
        <pre className="mt-3 overflow-x-auto text-xs">{JSON.stringify(query, null, 2)}</pre>
      </details>
    </>
  )
}
