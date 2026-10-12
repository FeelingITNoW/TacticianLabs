import type { ChampionRef, ItemRef, ReferenceLists, TraitRef } from '@/data/types'

export type EntityMatch =
  | { kind: 'champion'; ref: ChampionRef }
  | { kind: 'item'; ref: ItemRef }
  | { kind: 'trait'; ref: TraitRef }

export interface EntityMatcher {
  /** Looks up a whole string, e.g. an inline code span or a table cell */
  lookup(text: string): EntityMatch | null
  /** Splits text into plain strings and known units, items and traits */
  split(text: string): Array<string | EntityMatch>
}

const normalize = (text: string) => text.replace(/[‘’]/g, "'")
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Finds champion, item and trait names (and api names, which the model often prints) in text.
 * Longest name first, so "Radiant Infinity Edge" beats "Infinity Edge". Multi-word names match
 * in any case; single words must match exactly, so prose like "solar" or "hunter" stays text.
 * On a shared name a champion wins, then an item, then a trait.
 */
export function buildEntityMatcher(ref: ReferenceLists): EntityMatcher {
  const exact = new Map<string, EntityMatch>()
  const loose = new Map<string, EntityMatch>()

  const add = (key: string, match: EntityMatch) => {
    key = normalize(key)
    if (key.length < 2 || exact.has(key)) return
    exact.set(key, match)
    if (/\s/.test(key)) loose.set(key.toLowerCase(), match)
  }
  for (const ref_ of ref.champions) for (const k of [ref_.name, ref_.apiName]) add(k, { kind: 'champion', ref: ref_ })
  for (const ref_ of ref.items) for (const k of [ref_.name, ref_.apiName]) add(k, { kind: 'item', ref: ref_ })
  for (const ref_ of ref.traits) for (const k of [ref_.name, ref_.apiName]) add(k, { kind: 'trait', ref: ref_ })

  const keys = [...exact.keys()].sort((a, b) => b.length - a.length)
  const pattern = keys.length
    ? new RegExp(`(?<![\\p{L}\\p{N}_])(?:${keys.map(escape).join('|')})(?![\\p{L}\\p{N}_])`, 'giu')
    : null

  const lookup = (text: string): EntityMatch | null => {
    const key = normalize(text)
    return exact.get(key) ?? loose.get(key.toLowerCase()) ?? null
  }

  return {
    lookup,
    split(text) {
      if (!pattern) return [text]
      const out: Array<string | EntityMatch> = []
      let last = 0
      for (const m of normalize(text).matchAll(pattern)) {
        const match = lookup(m[0])
        if (!match) continue // a single word in the wrong case
        if (m.index > last) out.push(text.slice(last, m.index))
        out.push(match)
        last = m.index + m[0].length
      }
      if (last === 0) return [text]
      if (last < text.length) out.push(text.slice(last))
      return out
    },
  }
}
