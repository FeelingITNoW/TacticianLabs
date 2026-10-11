import '@tanstack/react-start/server-only'
import type { ItemStatRow } from '@/data/types'
import { runQuery, table } from './bigquery.server'
import { cached, MINUTE } from './cache.server'
import { getReference, itemRef } from './reference.server'

interface ItemStatQueryRow {
  api_name: string
  name: string | null
  item_type: string | null
  games: number
  win_rate: number | null
  top4_rate: number | null
  average_placement: number | null
  play_rate: number | null
  frequency: number | null
}

/** Every item with stats in the latest patch. The page splits them into tabs by type. */
export function getItemStats(): Promise<ItemStatRow[]> {
  return cached('items', 5 * MINUTE, async () => {
    const [rows, ref] = await Promise.all([
      runQuery<ItemStatQueryRow>(
        `SELECT api_name, name, item_type, games, win_rate, top4_rate, average_placement, play_rate, frequency
         FROM ${table('current_item_stats')}`,
        undefined,
        { fn: 'items' },
      ),
      getReference(),
    ])
    return rows.map((r) => ({
      ...itemRef(ref, r.api_name, r.name, r.item_type),
      games: r.games,
      winRate: r.win_rate ?? 0,
      top4Rate: r.top4_rate ?? 0,
      averagePlacement: r.average_placement ?? 0,
      playRate: r.play_rate ?? 0,
      frequency: r.frequency ?? 0,
    }))
  })
}
