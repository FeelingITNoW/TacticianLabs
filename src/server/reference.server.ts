import '@tanstack/react-start/server-only'
import type { ChampionRef, ItemRef, ItemType, ReferenceLists, TraitRef } from '@/data/types'
import { runQuery, table } from './bigquery.server'
import { cached, HOUR } from './cache.server'

const ITEM_TYPES = new Set<string>(['artifact', 'radiant', 'component', 'emblem', 'completed', 'misc'])

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

interface TraitRow {
  api_name: string
  name: string | null
  image: string | null
}

interface ItemRow extends TraitRow {
  item_type: string | null
}

/** Champion, trait and item names, costs, types and icons, keyed by Riot's api name. */
export function getReference(): Promise<Reference> {
  return cached('reference', HOUR, async () => {
    const [champions, traits, items] = await Promise.all([
      runQuery<ChampionRow>(`SELECT api_name, name, cost, image FROM ${table('champions')}`, undefined, {
        fn: 'reference.champions',
      }),
      runQuery<TraitRow>(`SELECT api_name, name, image FROM ${table('traits')}`, undefined, {
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
        traits.map((r) => [r.api_name, { apiName: r.api_name, name: r.name ?? r.api_name, image: r.image }]),
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
  return ref.traits.get(apiName) ?? { apiName, name: apiName, image: null }
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
