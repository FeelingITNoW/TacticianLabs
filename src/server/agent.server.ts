import '@tanstack/react-start/server-only'
import type { AgentAnswer, AgentTurn, RollOddsRow, RollOddsRun } from '@/data/types'

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
