import '@tanstack/react-start/server-only'
import type { ChampionRef, ItemRef, ItemType, ReferenceLists, TraitRef, TraitStyle } from '@/data/types'
import { runQuery, table } from './bigquery.server'
import { cached, HOUR } from './cache.server'

const ITEM_TYPES = new Set<string>(['artifact', 'radiant', 'component', 'emblem', 'completed', 'misc'])
const TRAIT_STYLES = new Set<string>(['bronze', 'silver', 'gold', 'prismatic', 'unique'])

export interface Reference {
  champions: Map<string, ChampionRef>
  traits: Map<string, TraitRef>
  items: Map<string, ItemRef>
}

interface ChampionRow {
  api_name: string
  name: string | null
  cost: number | null
  image: string | null
}

interface ItemRow {
  api_name: string
  name: string | null
  image: string | null
  item_type: string | null
}

interface TraitRow {
  api_name: string
  name: string | null
  image: string | null
  styles: string[] | null
}

/** Champion, trait and item names, costs, types and icons, keyed by Riot's api name. */
export function getReference(): Promise<Reference> {
  return cached('reference', HOUR, async () => {
    const [champions, traits, items] = await Promise.all([
      runQuery<ChampionRow>(`SELECT api_name, name, cost, image FROM ${table('champions')}`, undefined, {
        fn: 'reference.champions',
      }),
      runQuery<TraitRow>(`SELECT api_name, name, image, styles FROM ${table('traits')}`, undefined, {
        fn: 'reference.traits',
      }),
      runQuery<ItemRow>(`SELECT api_name, name, item_type, image FROM ${table('items')}`, undefined, {
        fn: 'reference.items',
      }),
    ])
    return {
      champions: new Map(
        champions.map((r) => [
          r.api_name,
          { apiName: r.api_name, name: r.name ?? r.api_name, cost: r.cost ?? 0, image: r.image },
        ]),
      ),
      traits: new Map(
        traits.map((r) => [
          r.api_name,
          {
            apiName: r.api_name,
            name: r.name ?? r.api_name,
            image: r.image,
            styles: (r.styles ?? []).filter((s): s is TraitStyle => TRAIT_STYLES.has(s)),
          },
        ]),
      ),
      items: new Map(
        items.map((r) => [
          r.api_name,
          {
            apiName: r.api_name,
            name: r.name ?? r.api_name,
            image: r.image,
            itemType: toItemType(r.item_type),
          },
        ]),
      ),
    }
  })
}

export function toItemType(value: string | null): ItemType | null {
  return value !== null && ITEM_TYPES.has(value) ? (value as ItemType) : null
}

/** An api name from the stats views that is missing from the reference tables still renders. */
export function championRef(ref: Reference, apiName: string, name?: string | null, cost?: number | null): ChampionRef {
  return ref.champions.get(apiName) ?? { apiName, name: name ?? apiName, cost: cost ?? 0, image: null }
}

export function itemRef(ref: Reference, apiName: string, name?: string | null, type?: string | null): ItemRef {
  return ref.items.get(apiName) ?? { apiName, name: name ?? apiName, image: null, itemType: toItemType(type ?? null) }
}

export function traitRef(ref: Reference, apiName: string): TraitRef {
  return ref.traits.get(apiName) ?? { apiName, name: apiName, image: null, styles: [] }
}

/** The style of a comp's average tier, rounded and kept within the trait's tiers. */
export function traitStyle(trait: TraitRef, avgTier: number): TraitStyle | null {
  if (trait.styles.length === 0) return null
  const tier = Math.min(Math.max(Math.round(avgTier), 1), trait.styles.length)
  return trait.styles[tier - 1]
}

export async function getReferenceLists(): Promise<ReferenceLists> {
  const ref = await getReference()
  const byName = <T extends { name: string }>(rows: Iterable<T>) =>
    [...rows].sort((a, b) => a.name.localeCompare(b.name))
  return {
    champions: byName(ref.champions.values()),
    traits: byName(ref.traits.values()),
    items: byName(ref.items.values()),
  }
}
