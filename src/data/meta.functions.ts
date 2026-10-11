import { createServerFn } from '@tanstack/react-start'

export const getMetaFn = createServerFn({ method: 'GET' }).handler(async () => {
  const { getMeta } = await import('@/server/meta.server')
  return getMeta()
})

export const getReferenceListsFn = createServerFn({ method: 'GET' }).handler(async () => {
  const { getReferenceLists } = await import('@/server/reference.server')
  return getReferenceLists()
})
