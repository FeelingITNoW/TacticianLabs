import '@tanstack/react-start/server-only'
import type {
  TriosResult,
  UnitItemization,
  UnitItemPairRow,
  UnitItemRow,
  UnitItemTrioRow,
  UnitRow,
} from '@/data/types'
import { runQuery, table, timestamp } from './bigquery.server'
import { cached, HOUR, MINUTE } from './cache.server'
import { getMeta, getPatchWindow } from './meta.server'
import { championRef, getReference, itemRef } from './reference.server'

interface StatColumns {
  games: number
  win_rate: number | null
  top4_rate: number | null
  average_placement: number | null
}

const stats = (r: StatColumns) => ({
  games: r.games,
  winRate: r.win_rate ?? 0,
  top4Rate: r.top4_rate ?? 0,
  averagePlacement: r.average_placement ?? 0,
})

interface UnitStatRow extends StatColumns {
  api_name: string
  name: string | null
  cost: number | null
  play_rate: number | null
  frequency: number | null
}

/** Every champion with stats in the latest patch. */
export function getUnits(): Promise<UnitRow[]> {
  return cached('units', 5 * MINUTE, async () => {
    const [rows, ref] = await Promise.all([
      runQuery<UnitStatRow>(
        `SELECT api_name, name, cost, games, win_rate, top4_rate, average_placement, play_rate, frequency
         FROM ${table('current_champion_stats')}`,
        undefined,
        { fn: 'units' },
      ),
      getReference(),
    ])
    return rows.map((r) => ({
      ...championRef(ref, r.api_name, r.name, r.cost),
      ...stats(r),
      playRate: r.play_rate ?? 0,
      frequency: r.frequency ?? 0,
    }))
  })
}

/** Known unit ids only: anything else never reaches BigQuery. */
export async function findUnit(apiName: string): Promise<UnitRow | null> {
  return (await getUnits()).find((u) => u.apiName === apiName) ?? null
}

interface UnitItemStatRow extends StatColumns {
  item: string
  item_name: string | null
  item_type: string | null
  share_of_champion_games: number | null
}

interface UnitPairStatRow extends StatColumns {
  item_a: string
  item_b: string
  item_a_name: string | null
  item_b_name: string | null
  item_a_type: string | null
  item_b_type: string | null
  share_of_champion_games: number | null
}

// Items and duos come from precomputed counters, so these are cheap. Rows are capped by
// games; the page filters further in the browser.
const MAX_ROWS = 300
const MIN_DUO_GAMES = 3

/** The unit's own stats, its best items and its item duos in the latest patch, or null for an unknown unit. */
export async function getItemization(unitId: string): Promise<UnitItemization | null> {
  // Checked before the cache, so ids that don't exist can't fill it
  const unit = await findUnit(unitId)
  if (!unit) return null
  return cached(`itemization:${unitId}`, 5 * MINUTE, async () => {
    const [ref, items, pairs] = await Promise.all([
      getReference(),
      runQuery<UnitItemStatRow>(
        `SELECT item, item_name, item_type, games, win_rate, top4_rate, average_placement, share_of_champion_games
         FROM ${table('current_champion_item_stats')}
         WHERE champion = @champion ORDER BY games DESC LIMIT ${MAX_ROWS}`,
        { champion: unitId },
        { fn: 'unit.items' },
      ),
      runQuery<UnitPairStatRow>(
        `SELECT item_a, item_b, item_a_name, item_b_name, item_a_type, item_b_type, games, win_rate, top4_rate,
           average_placement, share_of_champion_games
         FROM ${table('current_champion_item_pair_stats')}
         WHERE champion = @champion AND games >= ${MIN_DUO_GAMES} ORDER BY games DESC LIMIT ${MAX_ROWS}`,
        { champion: unitId },
        { fn: 'unit.duos' },
      ),
    ])
    const itemRows: UnitItemRow[] = items.map((r) => ({
      item: itemRef(ref, r.item, r.item_name, r.item_type),
      ...stats(r),
      share: r.share_of_champion_games ?? 0,
    }))
    const duoRows: UnitItemPairRow[] = pairs.map((r) => ({
      items: [itemRef(ref, r.item_a, r.item_a_name, r.item_a_type), itemRef(ref, r.item_b, r.item_b_name, r.item_b_type)],
      ...stats(r),
      share: r.share_of_champion_games ?? 0,
    }))
    return { unit, items: itemRows, duos: duoRows }
  })
}

interface TrioStatRow extends StatColumns {
  item_a: string
  item_b: string
  item_c: string
  item_a_name: string | null
  item_b_name: string | null
  item_c_name: string | null
  share_of_champion_games: number | null
}

// Trios have no counters (a unit's three items are its whole build), so they are counted from
// the match tables by the champion_item_trios function: ~1 GB per champion and growing with
// the patch. Cached for hours, and the floor is fixed so the cache stays one entry per champion.
const TRIOS_MIN_GAMES = 3
const TRIOS_MAX_BYTES = 10_000_000_000
const TRIOS_TTL = 6 * HOUR

export async function getTrios(unitId: string): Promise<TriosResult> {
  if (!(await findUnit(unitId))) return { error: 'Unknown unit' }
  return cached(`trios:${unitId}`, TRIOS_TTL, async () => {
    const { patch } = await getMeta()
    const window = await getPatchWindow(patch)
    const [ref, rows] = await Promise.all([
      getReference(),
      runQuery<TrioStatRow>(
        `SELECT item_a, item_b, item_c, item_a_name, item_b_name, item_c_name, games, win_rate, top4_rate,
           average_placement, share_of_champion_games
         FROM ${table('champion_item_trios')}(@champion, @patch, @lo, @hi, @min_games)
         ORDER BY games DESC LIMIT ${MAX_ROWS}`,
        {
          champion: unitId,
          patch,
          lo: timestamp(window.lo),
          hi: timestamp(window.hi),
          min_games: TRIOS_MIN_GAMES,
        },
        { fn: 'unit.trios', maxBytes: TRIOS_MAX_BYTES },
      ),
    ])
    const trios: UnitItemTrioRow[] = rows.map((r) => ({
      items: [
        itemRef(ref, r.item_a, r.item_a_name),
        itemRef(ref, r.item_b, r.item_b_name),
        itemRef(ref, r.item_c, r.item_c_name),
      ],
      ...stats(r),
      share: r.share_of_champion_games ?? 0,
    }))
    return { rows: trios }
  })
}
