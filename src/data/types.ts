// DTOs shared by the server functions and the pages. Plain JSON only: server code maps
// BigQuery rows into these explicitly, so a column rename can't leak through to the client.

export type ItemType = 'artifact' | 'radiant' | 'component' | 'emblem' | 'completed' | 'misc'

export interface Entity {
  apiName: string
  name: string
  /** Icon URL: Data Dragon for items and traits, CommunityDragon for champions */
  image: string | null
}

export interface ChampionRef extends Entity {
  cost: number
}

export interface ItemRef extends Entity {
  /** null when the item is not in the reference table or has an unknown type */
  itemType: ItemType | null
}

/** What an active trait looks like in game, per tier */
export type TraitStyle = 'bronze' | 'silver' | 'gold' | 'prismatic' | 'unique'

export interface TraitRef extends Entity {
  /** Style of each tier, in order: styles[tier - 1]. Empty when unknown. */
  styles: TraitStyle[]
}

export interface ReferenceLists {
  champions: ChampionRef[]
  traits: TraitRef[]
  items: ItemRef[]
}

/** The patch every page shows. `patch` is Data Dragon's version at ingest time. */
export interface Meta {
  patch: string
  matches: number
  boards: number
  lastPlayedAt: number
}

/** Rates are 0..1, average placement 1..8 (lower is better). */
export interface Stats {
  games: number
  winRate: number
  top4Rate: number
  averagePlacement: number
}

export interface UnitRow extends ChampionRef, Stats {
  playRate: number
  /** boards per match in the patch, 0..8 */
  frequency: number
}

export interface ItemStatRow extends ItemRef, Stats {
  /** boards per match that had the item, 1..8 */
  playRate: number
  frequency: number
}

/** One item on one unit. `share` is the part of the unit's boards that held it. */
export interface UnitItemRow extends Stats {
  item: ItemRef
  share: number
}

export interface UnitItemPairRow extends Stats {
  items: [ItemRef, ItemRef]
  share: number
}

export interface UnitItemTrioRow extends Stats {
  items: [ItemRef, ItemRef, ItemRef]
  share: number
}

export interface UnitItemization {
  unit: UnitRow
  items: UnitItemRow[]
  duos: UnitItemPairRow[]
}

/** Trios are queried on demand, so they carry their own failure instead of breaking the page. */
export type TriosResult = { rows: UnitItemTrioRow[] } | { error: string }

export type CompCategory = '1_cost_reroll' | '2_cost_reroll' | '3_cost_reroll' | 'fast_8' | 'fast_9'

export interface CompUnit extends ChampionRef {
  frequency: number
  avgItems: number
  avgStar: number
  carry: boolean
}

export interface CompTrait extends TraitRef {
  frequency: number
  avgTier: number
  /** Style of the comp's average tier, rounded; null when the trait's styles are unknown */
  style: TraitStyle | null
}

export interface CompRow extends Stats {
  compId: string
  label: string
  /** null on comps clustered before categories existed */
  category: CompCategory | null
  playRate: number
  frequency: number
  units: CompUnit[]
  traits: CompTrait[]
}

export interface VariantDiff {
  kind: 'unit' | 'trait'
  change: 'added' | 'removed'
  apiName: string
  name: string
  image: string | null
}

/** A comp's variant: the same comp played with a few different units or traits */
export interface VariantRow extends Stats {
  compId: string
  compLabel: string
  variantId: string
  label: string
  /** Share of the comp's boards that fit the variant (0-1) */
  shareOfComp: number
  units: CompUnit[]
  traits: CompTrait[]
  diff: VariantDiff[]
}

export type Tier = 'CHALLENGER' | 'GRANDMASTER' | 'MASTER'

export interface LeaderboardRow {
  rank: number
  gameName: string | null
  tagLine: string | null
  region: string
  tier: Tier
  division: string | null
  leaguePoints: number
  /** Riot's league `wins` are top-4 finishes, `losses` the rest */
  top4: number
  games: number
  hotStreak: boolean
}

export interface LeaderboardRegion {
  region: string
  players: number
  refreshedAt: number
}

export interface LeaderboardPage {
  rows: LeaderboardRow[]
  total: number
  pageSize: number
  regions: LeaderboardRegion[]
}

/** One turn of the /ask chat, as the agent service takes it. */
export interface AgentTurn {
  role: 'user' | 'model'
  text: string
}

export interface AgentAnswer {
  text: string
  /** The SQL the agent ran, in order */
  queries: string[]
}
