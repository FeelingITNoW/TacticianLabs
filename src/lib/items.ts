import type { ItemType } from '@/data/types'

export const ITEM_TABS = [
  { id: 'completed', label: 'Completed', types: ['completed'] },
  { id: 'artifacts', label: 'Artifacts', types: ['artifact'] },
  { id: 'radiant', label: 'Radiant', types: ['radiant'] },
  { id: 'emblems', label: 'Emblems', types: ['emblem'] },
  // Boosters, potions, consumables, chests, and any item whose type isn't known
  { id: 'misc', label: 'Misc', types: ['misc'] },
] as const satisfies readonly { id: string; label: string; types: readonly ItemType[] }[]

export type ItemTabId = (typeof ITEM_TABS)[number]['id']

export const ITEM_TAB_IDS = ITEM_TABS.map((t) => t.id) as [ItemTabId, ...ItemTabId[]]

/** The tab an item shows on. Components have none: they are only ever built into other items. */
export function tabForItemType(type: ItemType | null): ItemTabId | null {
  if (type === 'component') return null
  const tab = ITEM_TABS.find((t) => (t.types as readonly string[]).includes(type ?? ''))
  return tab?.id ?? 'misc'
}

export const ITEM_TYPE_LABELS: Record<ItemType, string> = {
  completed: 'Completed',
  artifact: 'Artifact',
  radiant: 'Radiant',
  emblem: 'Emblem',
  misc: 'Misc',
  component: 'Component',
}
