import '@tanstack/react-start/server-only'
import type { CompCategory, CompRow } from '@/data/types'
import { runQuery, table } from './bigquery.server'
import { cached, MINUTE } from './cache.server'
import { championRef, getReference, traitRef } from './reference.server'

const CATEGORIES = new Set<string>(['1_cost_reroll', '2_cost_reroll', '3_cost_reroll', 'fast_8', 'fast_9'])

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
  units: { api_name: string; frequency: number | null; avg_items: number | null; avg_star: number | null }[]
  traits: { api_name: string; frequency: number | null; avg_tier: number | null }[]
  carries: string[]
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
        units: (r.units ?? []).map((u) => ({
          ...championRef(ref, u.api_name),
          frequency: u.frequency ?? 0,
          avgItems: u.avg_items ?? 0,
          avgStar: u.avg_star ?? 0,
          carry: carries.has(u.api_name),
        })),
        traits: (r.traits ?? []).map((t) => ({
          ...traitRef(ref, t.api_name),
          frequency: t.frequency ?? 0,
          avgTier: t.avg_tier ?? 0,
        })),
      }
    })
  })
}

export async function getComp(compId: string): Promise<CompRow | null> {
  return (await getComps()).find((c) => c.compId === compId) ?? null
}
