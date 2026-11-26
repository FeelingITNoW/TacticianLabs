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

export interface RollOddsRow {
  gold: number
  rolls: number
  /** Odds of buying every copy of every unit, 0 to 1 */
  allUnits: number
  /** Odds of each unit's copies alone, by unit name */
  perUnit: Record<string, number>
}

/** One roll_odds call the agent made: what it asked and what came back */
export interface RollOddsRun {
  level: number
  units: { name: string; cost: number; copies: number; copiesOut: number }[]
  /** Copies of a cost gone from the pool that aren't the units' own */
  tierOut: { cost: number; copies: number }[]
  /** The odds at the amounts of gold the agent asked about */
  results: RollOddsRow[]
  /** The odds after every roll, from when the copies are paid for to about 95%: what the chart draws */
  curve: RollOddsRow[]
}

/** What a projection has at a round's planning phase, before spending; the totals run since the start */
export interface GoldProjectionPoint {
  round: string
  kind: 'pvp' | 'carousel' | 'neutral'
  /** What is held after the round's own spending */
  gold: number
  /** The Free Rolls at what a roll costs, and the gold with them */
  freeRollGold: number
  totalGold: number
  naturalXp: number
  augmentXp: number
  /** XP bought with gold, up to and including this round */
  boughtXp: number
  freeRolls: number
  /** Gold this round spent on units and gained, and spent on XP */
  spent: number
  gained: number
  leveling: number
  /** The level this round's XP, bought included, reaches */
  level: number
  /** What this round added to the gold, by source (averages, so maybe not whole, in the mixed scenario) */
  income: { interest: number; passive: number; reward: number; carousel: number; augment: number }
}

/** One step of the XP curve; what is missing and costs at the end round is per Scenario */
export interface GoldProjectionCurveLevel {
  level: number
  /** XP from the level below */
  xp: number
  /** XP from the start of the projection */
  totalXp: number
  /** The round the XP reaches this level, bought XP included, if it does by the end round */
  reachedAt: string | null
  xpMissing: number
  goldCost: number
}

/** What reaching a level costs: the XP still missing, the gold that buys it, and what is left to roll with, Free Rolls included (negative is a shortfall of gold) */
export interface GoldProjectionLevel {
  xpMissing: number
  goldCost: number
  leftover: number
}

export type GoldProjectionPreset = 'win' | 'mixed' | 'loss'

export interface GoldProjectionScenario {
  label: string
  /** The preset it is, or null for a custom plan */
  preset: GoldProjectionPreset | null
  /** A custom plan's fights, a letter per PvP fight, w or l */
  fights: string | null
  /** True when nothing is spent, so the gold is a ceiling */
  ceiling: boolean
  /** What is held after the end round's spending */
  gold: number
  /** The Free Rolls at what a roll costs, and the gold with them */
  freeRollGold: number
  totalGold: number
  naturalXp: number
  augmentXp: number
  boughtXp: number
  freeRolls: number
  /** Gold spent on units and gained over the projection, and spent on XP */
  spent: number
  gained: number
  leveling: number
  /** The level the XP, bought included, reaches */
  level: number
  /** By target level, 8 and 9 */
  levels: Record<string, GoldProjectionLevel>
  /** Every level from the start's to 9 */
  levelCurve: GoldProjectionCurveLevel[]
  /** One point per round from the start to the end round: what the charts draw */
  series: GoldProjectionPoint[]
}

/** One gold_projection call the agent made: what it asked and what came back */
export interface GoldProjectionRun {
  endRound: string
  start: { round: string; level: number; xp: number; gold: number; streak: number }
  augments: { name: string; slot: string; gold: number; freeRolls: number; xpPerRound: number; maxInterest: number }[]
  scenarios: GoldProjectionScenario[]
}

export interface AgentAnswer {
  text: string
  /** The SQL the agent ran, in order */
  queries: string[]
  /** The roll odds the agent worked out, in order */
  rollOdds: RollOddsRun[]
  /** The gold projections the agent worked out, in order */
  goldProjections: GoldProjectionRun[]
}
