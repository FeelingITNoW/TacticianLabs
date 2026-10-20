import { createServerFn } from '@tanstack/react-start'
import { z } from 'zod'

// Same limits as include/insights/server.py
const input = z.object({
  question: z.string().trim().min(1).max(500),
  history: z
    .array(z.object({ role: z.enum(['user', 'model']), text: z.string().min(1).max(8000) }))
    .max(12)
    .default([]),
  conversation_id: z.string().uuid().optional(),
})

export const askAgentFn = createServerFn({ method: 'POST' })
  .inputValidator(input)
  .handler(async ({ data }) => {
    const { askAgent } = await import('@/server/agent.server')
    return askAgent(data.question, data.history, data.conversation_id)
  })
