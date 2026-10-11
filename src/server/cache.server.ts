import '@tanstack/react-start/server-only'

// The data refreshes once a day, so every read is cached. The cache holds the *promise*, so
// identical requests that arrive while a query is running share it instead of starting more.
const MAX_ENTRIES = 500

interface Entry {
  expires: number
  value: Promise<unknown>
}

const store = new Map<string, Entry>()

export function cached<T>(key: string, ttlMs: number, load: () => Promise<T>): Promise<T> {
  const now = Date.now()
  const hit = store.get(key)
  if (hit && hit.expires > now) return hit.value as Promise<T>

  const value = load()
  const entry: Entry = { expires: now + ttlMs, value }
  store.delete(key) // re-insert so the oldest entry is always first
  store.set(key, entry)
  if (store.size > MAX_ENTRIES) store.delete(store.keys().next().value as string)

  // A failure must not be served again from the cache
  value.catch(() => {
    if (store.get(key) === entry) store.delete(key)
  })
  return value
}

export const MINUTE = 60_000
export const HOUR = 60 * MINUTE
