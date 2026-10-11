import { createServerFn } from '@tanstack/react-start'
import { z } from 'zod'

export const getCompsFn = createServerFn({ method: 'GET' }).handler(async () => {
  const { getComps } = await import('@/server/compositions.server')
  return getComps()
})

/** One comp from the latest patch, or null: comp ids change when comps are re-clustered. */
export const getCompFn = createServerFn({ method: 'GET' })
  .inputValidator(z.object({ compId: z.string().min(1).max(64) }))
  .handler(async ({ data }) => {
    const { getComp } = await import('@/server/compositions.server')
    return getComp(data.compId)
  })
