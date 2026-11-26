import '@tanstack/react-start/server-only'
import type {
  AgentAnswer,
  AgentTurn,
  GoldProjectionPoint,
  GoldProjectionPreset,
  GoldProjectionRun,
  GoldProjectionScenario,
  RollOddsRow,
  RollOddsRun,
} from '@/data/types'

// The SQL agent is a separate Python service (include/insights/server.py)
const AGENT_URL = process.env.AGENT_URL ?? 'http://127.0.0.1:8001'
const TIMEOUT_MS = 120_000

/** Asks the agent. Failures are logged here and rethrown as a message that is safe to show. */
export async function askAgent(
  question: string,
  history: AgentTurn[],
  conversationId?: string,
): Promise<AgentAnswer> {
  let response: Response
  try {
    response = await fetch(`${AGENT_URL}/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question, history, conversation_id: conversationId }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    })
  } catch (error) {
    console.error('Agent request failed:', error)
    if (error instanceof Error && error.name === 'TimeoutError') throw new Error('The agent took too long to answer')
    throw new Error("The agent service isn't running")
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null
    console.error(`Agent returned ${response.status}:`, body)
    throw new Error(response.status === 400 && body?.error ? body.error : 'The agent failed to answer')
  }
  const body = (await response.json()) as AgentBody
  return {
    text: body.text,
    queries: body.queries ?? [],
    rollOdds: (body.roll_odds ?? []).map(toRollOdds),
    goldProjections: (body.gold_projections ?? []).map(toGoldProjection),
  }
}

// The agent's JSON, in its snake_case
interface AgentBody {
  text: string
  queries?: string[]
  roll_odds?: {
    level: number
    units: { name: string; cost: number; copies: number; copies_out: number }[]
    tier_out: { cost: number; copies: number }[]
    results: RawRollOddsRow[]
    curve: RawRollOddsRow[]
  }[]
  gold_projections?: RawGoldProjection[]
}

interface RawRollOddsRow {
  gold: number
  rolls: number
  all_units: number
  per_unit: Record<string, number>
}

function toRollOdds(run: NonNullable<AgentBody['roll_odds']>[number]): RollOddsRun {
  return {
    level: run.level,
    units: run.units.map((unit) => ({
      name: unit.name,
      cost: unit.cost,
      copies: unit.copies,
      copiesOut: unit.copies_out,
    })),
    tierOut: run.tier_out,
    results: run.results.map(toRollOddsRow),
    curve: run.curve.map(toRollOddsRow),
  }
}

function toRollOddsRow(row: RawRollOddsRow): RollOddsRow {
  return { gold: row.gold, rolls: row.rolls, allUnits: row.all_units, perUnit: row.per_unit }
}

interface RawGoldProjectionPoint {
  round: string
  kind: GoldProjectionPoint['kind']
  gold: number
  free_roll_gold: number
  total_gold: number
  natural_xp: number
  augment_xp: number
  bought_xp: number
  free_rolls: number
  spent: number
  gained: number
  leveling: number
  level: number
  income: GoldProjectionPoint['income']
}

interface RawGoldProjectionCurveLevel {
  level: number
  xp: number
  total_xp: number
  reached_at: string | null
  xp_missing: number
  gold_cost: number
}

interface RawGoldProjectionScenario {
  label: string
  preset: GoldProjectionPreset | null
  fights: string | null
  ceiling: boolean
  gold: number
  free_roll_gold: number
  total_gold: number
  natural_xp: number
  augment_xp: number
  bought_xp: number
  free_rolls: number
  spent: number
  gained: number
  leveling: number
  level: number
  levels: Record<string, { xp_missing: number; gold_cost: number; leftover: number }>
  level_curve: RawGoldProjectionCurveLevel[]
  series: RawGoldProjectionPoint[]
}

interface RawGoldProjection {
  end_round: string
  start: GoldProjectionRun['start']
  augments: { name: string; slot: string; gold: number; free_rolls: number; xp_per_round: number; max_interest: number }[]
  scenarios: RawGoldProjectionScenario[]
}

function toGoldProjection(run: RawGoldProjection): GoldProjectionRun {
  const scenario = (raw: RawGoldProjectionScenario): GoldProjectionScenario => ({
    label: raw.label,
    preset: raw.preset,
    fights: raw.fights,
    ceiling: raw.ceiling,
    gold: raw.gold,
    freeRollGold: raw.free_roll_gold,
    totalGold: raw.total_gold,
    naturalXp: raw.natural_xp,
    augmentXp: raw.augment_xp,
    boughtXp: raw.bought_xp,
    freeRolls: raw.free_rolls,
    spent: raw.spent,
    gained: raw.gained,
    leveling: raw.leveling,
    level: raw.level,
    levels: Object.fromEntries(
      Object.entries(raw.levels).map(([level, row]) => [
        level,
        { xpMissing: row.xp_missing, goldCost: row.gold_cost, leftover: row.leftover },
      ]),
    ),
    levelCurve: raw.level_curve.map((row) => ({
      level: row.level,
      xp: row.xp,
      totalXp: row.total_xp,
      reachedAt: row.reached_at,
      xpMissing: row.xp_missing,
      goldCost: row.gold_cost,
    })),
    series: raw.series.map(toGoldProjectionPoint),
  })
  return {
    endRound: run.end_round,
    start: run.start,
    augments: run.augments.map((a) => ({
      name: a.name,
      slot: a.slot,
      gold: a.gold,
      freeRolls: a.free_rolls,
      xpPerRound: a.xp_per_round,
      maxInterest: a.max_interest,
    })),
    scenarios: run.scenarios.map(scenario),
  }
}

function toGoldProjectionPoint(point: RawGoldProjectionPoint): GoldProjectionPoint {
  return {
    round: point.round,
    kind: point.kind,
    gold: point.gold,
    freeRollGold: point.free_roll_gold,
    totalGold: point.total_gold,
    naturalXp: point.natural_xp,
    augmentXp: point.augment_xp,
    boughtXp: point.bought_xp,
    freeRolls: point.free_rolls,
    spent: point.spent,
    gained: point.gained,
    leveling: point.leveling,
    level: point.level,
    income: point.income,
  }
}
