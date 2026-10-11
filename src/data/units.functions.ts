import { createServerFn } from '@tanstack/react-start'
import { z } from 'zod'
import type { TriosResult } from './types'

const unitInput = z.object({ unitId: z.string().min(1).max(120) })

export const getUnitsFn = createServerFn({ method: 'GET' }).handler(async () => {
  const { getUnits } = await import('@/server/units.server')
  return getUnits()
})

/** The unit with its best items and duos, or null if there is no such unit. */
export const getItemizationFn = createServerFn({ method: 'GET' })
  .inputValidator(unitInput)
  .handler(async ({ data }) => {
    const { getItemization } = await import('@/server/units.server')
    return getItemization(data.unitId)
  })

/** Trios are queried on demand and can fail on their own, so a failure is data, not a thrown error. */
export const getTriosFn = createServerFn({ method: 'GET' })
  .inputValidator(unitInput)
  .handler(async ({ data }): Promise<TriosResult> => {
    const { getTrios } = await import('@/server/units.server')
    try {
      return await getTrios(data.unitId)
    } catch {
      return { error: 'The item trios could not be loaded right now.' }
    }
  })
