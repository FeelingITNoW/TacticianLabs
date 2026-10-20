import '@tanstack/react-start/server-only'
import type { CompCategory, CompRow, CompTrait, CompUnit, VariantDiff, VariantRow } from '@/data/types'
import { runQuery, table } from './bigquery.server'
import { cached, MINUTE } from './cache.server'
import { championRef, getReference, traitRef, traitStyle, type Reference } from './reference.server'

const CATEGORIES = new Set<string>(['1_cost_reroll', '2_cost_reroll', '3_cost_reroll', 'fast_8', 'fast_9'])

interface UnitQueryRow {
  api_name: string
  frequency: number | null
  avg_items: number | null
  avg_star: number | null
}

interface TraitQueryRow {
  api_name: string
  frequency: number | null
  avg_tier: number | null
}

interface CompQueryRow {
  comp_id: string
  label: string | null
  category: string | null
  games: number
  win_rate: number | null
  top4_rate: number | null
  average_placement: number | null
  play_rate: number | null
  frequency: number | null
  units: UnitQueryRow[]
  traits: TraitQueryRow[]
  carries: string[]
}

interface VariantQueryRow {
  comp_id: string
  comp_label: string | null
  variant_id: string
  label: string | null
  games: number
  win_rate: number | null
  top4_rate: number | null
  average_placement: number | null
  share_of_comp: number | null
  units: UnitQueryRow[]
  traits: TraitQueryRow[]
  diff: { api_name: string; kind: string; change: string }[]
}

function mapUnits(ref: Reference, rows: UnitQueryRow[] | null, carries: Set<string>): CompUnit[] {
  return (rows ?? []).map((u) => ({
    ...championRef(ref, u.api_name),
    frequency: u.frequency ?? 0,
    avgItems: u.avg_items ?? 0,
    avgStar: u.avg_star ?? 0,
    carry: carries.has(u.api_name),
  }))
}

function mapTraits(ref: Reference, rows: TraitQueryRow[] | null): CompTrait[] {
  return (rows ?? []).map((t) => {
    const trait = traitRef(ref, t.api_name)
    const avgTier = t.avg_tier ?? 0
    return { ...trait, frequency: t.frequency ?? 0, avgTier, style: traitStyle(trait, avgTier) }
  })
}

/** The latest patch's comps, best average placement first. Names and icons are added here. */
export function getComps(): Promise<CompRow[]> {
  return cached('comps', 5 * MINUTE, async () => {
    const [rows, ref] = await Promise.all([
      runQuery<CompQueryRow>(
        `SELECT comp_id, label, category, games, win_rate, top4_rate, average_placement, play_rate, frequency,
           units, traits, carries
         FROM ${table('current_composition_stats')} ORDER BY average_placement`,
        undefined,
        { fn: 'comps' },
      ),
      getReference(),
    ])
    return rows.map((r): CompRow => {
      const carries = new Set(r.carries ?? [])
      return {
        compId: r.comp_id,
        label: r.label ?? 'Unnamed comp',
        category: r.category && CATEGORIES.has(r.category) ? (r.category as CompCategory) : null,
        games: r.games,
        winRate: r.win_rate ?? 0,
        top4Rate: r.top4_rate ?? 0,
        averagePlacement: r.average_placement ?? 0,
        playRate: r.play_rate ?? 0,
        frequency: r.frequency ?? 0,
        units: mapUnits(ref, r.units, carries),
        traits: mapTraits(ref, r.traits),
      }
    })
  })
}

export async function getComp(compId: string): Promise<CompRow | null> {
  return (await getComps()).find((c) => c.compId === compId) ?? null
}

/** The latest patch's comp variants, each with its own units, traits and stats. */
export function getVariants(): Promise<VariantRow[]> {
  return cached('variants', 5 * MINUTE, async () => {
    const [rows, ref, comps] = await Promise.all([
      runQuery<VariantQueryRow>(
        `SELECT comp_id, comp_label, variant_id, label, games, win_rate, top4_rate, average_placement,
           share_of_comp, units, traits, diff
         FROM ${table('current_composition_variant_stats')} ORDER BY average_placement`,
        undefined,
        { fn: 'variants' },
      ),
      getReference(),
      getComps(),
    ])
    const carriesOf = new Map(comps.map((c) => [c.compId, new Set(c.units.filter((u) => u.carry).map((u) => u.apiName))]))
    return rows.map((r): VariantRow => ({
      compId: r.comp_id,
      compLabel: r.comp_label ?? 'Unnamed comp',
      variantId: r.variant_id,
      label: r.label ?? 'Unnamed variant',
      games: r.games,
      winRate: r.win_rate ?? 0,
      top4Rate: r.top4_rate ?? 0,
      averagePlacement: r.average_placement ?? 0,
      shareOfComp: r.share_of_comp ?? 0,
      units: mapUnits(ref, r.units, carriesOf.get(r.comp_id) ?? new Set()),
      traits: mapTraits(ref, r.traits),
      diff: (r.diff ?? []).flatMap((d): VariantDiff[] => {
        if ((d.kind !== 'unit' && d.kind !== 'trait') || (d.change !== 'added' && d.change !== 'removed')) return []
        const entity = d.kind === 'unit' ? championRef(ref, d.api_name) : traitRef(ref, d.api_name)
        return [{ kind: d.kind, change: d.change, apiName: d.api_name, name: entity.name, image: entity.image }]
      }),
    }))
  })
}
