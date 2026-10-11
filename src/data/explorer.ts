import { z } from 'zod'

// The request and response a data explorer backend would exchange. Only the contract exists:
// there is no server function and no query behind it yet, so the explorer page can't run it.
//
// A backend would answer it with a parameterized query over participant_units, unit_items,
// participant_traits, participants and matches, bounded by the patch window the same way the
// item trios are (see getPatchWindow in src/server/meta.server.ts).

export const GROUP_BY = ['units', 'items', 'traits'] as const

export const explorerQuerySchema = z.object({
  /** What each result row is */
  groupBy: z.enum(GROUP_BY).default('units').catch('units'),
  /** Boards must field every one of these units */
  units: z
    .array(
      z.object({
        apiName: z.string().max(120),
        /** Lowest star level the unit may have */
        minStar: z.number().int().min(1).max(3).optional(),
        /** Items the unit must hold */
        items: z.array(z.string().max(120)).max(3).optional(),
      }),
    )
    .max(10)
    .default([]).catch([]),
  /** Boards must have every one of these traits active */
  traits: z
    .array(z.object({ apiName: z.string().max(120), minTier: z.number().int().min(1).max(6).optional() }))
    .max(10)
    .default([]).catch([]),
  /** Boards must hold every one of these items somewhere */
  items: z.array(z.string().max(120)).max(10).default([]).catch([]),
})

export type ExplorerQuery = z.infer<typeof explorerQuerySchema>

export interface ExplorerResultRow {
  apiName: string
  games: number
  averagePlacement: number
  top4Rate: number
  winRate: number
  /** Average placement minus the average of all boards matching the filters */
  deltaPlacement: number
}

export interface ExplorerResult {
  /** Boards that matched every filter */
  matchedBoards: number
  rows: ExplorerResultRow[]
}

export const EMPTY_QUERY: ExplorerQuery = { groupBy: 'units', units: [], traits: [], items: [] }

export function isEmptyQuery(query: ExplorerQuery): boolean {
  return query.units.length === 0 && query.traits.length === 0 && query.items.length === 0
}
