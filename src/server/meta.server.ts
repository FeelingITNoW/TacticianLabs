import '@tanstack/react-start/server-only'
import type { Meta } from '@/data/types'
import { runQuery, table } from './bigquery.server'
import { cached, MINUTE } from './cache.server'

// Same value as TFT_RANKED_QUEUE_ID in include/riot_api/constants.py
export const RANKED_QUEUE_ID = 1100

interface MetaRow {
  patch: string
  matches: number
  boards: number
  last_played_ms: number
}

/** The newest patch, by the same rule as the current_* views: the one played most recently. */
export function getMeta(): Promise<Meta> {
  return cached('meta', 5 * MINUTE, async () => {
    const rows = await runQuery<MetaRow>(
      `SELECT patch, matches, boards, UNIX_MILLIS(last_played_at) AS last_played_ms
       FROM ${table('patch_totals')} ORDER BY last_played_at DESC LIMIT 1`,
      undefined,
      { fn: 'meta' },
    )
    if (rows.length === 0) throw new Error('No ranked matches have been ingested yet')
    const [row] = rows
    return {
      patch: row.patch,
      matches: row.matches,
      boards: row.boards,
      lastPlayedAt: row.last_played_ms,
    }
  })
}

export interface PatchWindow {
  /** First and last play time of the patch's ranked matches, in ms */
  lo: number
  hi: number
}

/**
 * Every per-match table is partitioned on played_at, so queries over them must pass the
 * patch's window or they scan the whole history (same as patch_window in data_aggregation.py).
 */
export function getPatchWindow(patch: string): Promise<PatchWindow> {
  return cached(`window:${patch}`, 5 * MINUTE, async () => {
    const rows = await runQuery<{ lo_ms: number | null; hi_ms: number | null }>(
      `SELECT UNIX_MILLIS(MIN(played_at)) AS lo_ms, UNIX_MILLIS(MAX(played_at)) AS hi_ms
       FROM ${table('matches')} WHERE game_version = @patch AND queue_id = ${RANKED_QUEUE_ID}`,
      { patch },
      { fn: 'meta.window' },
    )
    const { lo_ms, hi_ms } = rows[0] ?? {}
    if (lo_ms == null || hi_ms == null) throw new Error(`No ranked matches in patch ${patch}`)
    // hi is padded by a second so a match played in its last millisecond is never cut off
    return { lo: lo_ms, hi: hi_ms + 1000 }
  })
}
