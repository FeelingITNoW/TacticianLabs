import '@tanstack/react-start/server-only'
import type { LeaderboardPage, LeaderboardRegion, LeaderboardRow, Tier } from '@/data/types'
import { runQuery, table } from './bigquery.server'
import { cached, MINUTE } from './cache.server'

export const PAGE_SIZE = 100

const TIERS = new Set<string>(['CHALLENGER', 'GRANDMASTER', 'MASTER'])

interface LadderQueryRow {
  game_name: string | null
  tag_line: string | null
  region: string
  tier: string
  division: string | null
  league_points: number
  wins: number
  losses: number
  hot_streak: boolean | null
  region_rank: number
  refreshed_ms: number
}

interface LadderEntry extends Omit<LeaderboardRow, 'rank'> {
  regionRank: number
  globalRank: number
  /** lower-cased "name#tag", for searching */
  search: string
}

interface Ladder {
  entries: LadderEntry[]
  regions: LeaderboardRegion[]
}

const TIER_ORDER: Record<Tier, number> = { CHALLENGER: 0, GRANDMASTER: 1, MASTER: 2 }

// ~38k players, a few MB: read once and filtered here, because paging in SQL would cost a
// BigQuery round trip per page. The ingest refreshes it daily.
function getLadder(): Promise<Ladder> {
  return cached('ladder', 15 * MINUTE, async () => {
    const rows = await runQuery<LadderQueryRow>(
      `SELECT game_name, tag_line, region, tier, \`rank\` AS division, league_points, wins, losses, hot_streak,
         region_rank, UNIX_MILLIS(region_refreshed_at) AS refreshed_ms
       FROM ${table('leaderboard')}`,
      undefined,
      { fn: 'leaderboard', maxBytes: 100_000_000 },
    )

    const entries: LadderEntry[] = rows
      .filter((r) => TIERS.has(r.tier))
      .map((r) => ({
        gameName: r.game_name,
        tagLine: r.tag_line,
        region: r.region,
        tier: r.tier as Tier,
        division: r.division,
        leaguePoints: r.league_points,
        top4: r.wins,
        games: r.wins + r.losses,
        hotStreak: r.hot_streak ?? false,
        regionRank: r.region_rank,
        globalRank: 0,
        search: `${r.game_name ?? ''}#${r.tag_line ?? ''}`.toLowerCase(),
      }))

    // Best first across every region: tier, then league points
    entries.sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier] || b.leaguePoints - a.leaguePoints)
    entries.forEach((e, i) => (e.globalRank = i + 1))

    const regions = new Map<string, LeaderboardRegion>()
    for (const r of rows) {
      const region = regions.get(r.region) ?? { region: r.region, players: 0, refreshedAt: r.refreshed_ms }
      region.players += 1
      regions.set(r.region, region)
    }
    return { entries, regions: [...regions.values()].sort((a, b) => b.players - a.players) }
  })
}

export interface LadderQuery {
  region?: string
  tier?: Tier
  q?: string
  page: number
}

export async function getLeaderboard({ region, tier, q, page }: LadderQuery): Promise<LeaderboardPage> {
  const ladder = await getLadder()
  const knownRegion = region !== undefined && ladder.regions.some((r) => r.region === region) ? region : undefined
  const needle = q?.trim().toLowerCase()

  let entries = ladder.entries
  if (knownRegion) entries = entries.filter((e) => e.region === knownRegion)
  if (tier) entries = entries.filter((e) => e.tier === tier)
  if (needle) entries = entries.filter((e) => e.search.includes(needle))

  // Ranks are the player's place on the whole ladder (or their region's), not in the filtered list
  const rank = (e: LadderEntry) => (knownRegion ? e.regionRank : e.globalRank)
  entries = [...entries].sort((a, b) => rank(a) - rank(b))

  const start = (Math.max(1, page) - 1) * PAGE_SIZE
  const rows = entries.slice(start, start + PAGE_SIZE).map(
    ({ regionRank, globalRank, search, ...row }): LeaderboardRow => ({
      ...row,
      rank: knownRegion ? regionRank : globalRank,
    }),
  )
  return { rows, total: entries.length, pageSize: PAGE_SIZE, regions: ladder.regions }
}
