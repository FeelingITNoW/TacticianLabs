import { createServerFn } from '@tanstack/react-start'
import { z } from 'zod'

const input = z.object({
  region: z.string().max(10).optional(),
  tier: z.enum(['CHALLENGER', 'GRANDMASTER', 'MASTER']).optional(),
  q: z.string().max(60).optional(),
  page: z.number().int().min(1).max(10_000),
})

export const getLeaderboardFn = createServerFn({ method: 'GET' })
  .inputValidator(input)
  .handler(async ({ data }) => {
    const { getLeaderboard } = await import('@/server/leaderboard.server')
    return getLeaderboard(data)
  })
