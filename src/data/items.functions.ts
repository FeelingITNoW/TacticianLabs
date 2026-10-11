import { createServerFn } from '@tanstack/react-start'

export const getItemStatsFn = createServerFn({ method: 'GET' }).handler(async () => {
  const { getItemStats } = await import('@/server/items.server')
  return getItemStats()
})
