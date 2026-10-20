import '@tanstack/react-start/server-only'
import type { AgentAnswer, AgentTurn } from '@/data/types'

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
  const body = (await response.json()) as AgentAnswer
  return { text: body.text, queries: body.queries ?? [] }
}
