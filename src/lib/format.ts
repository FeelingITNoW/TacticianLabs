/** 0.2345 -> "23.5%" */
export function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`
}

/** Average placement, 1 (best) to 8 */
export function placement(value: number): string {
  return value.toFixed(2)
}

const compactFormat = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

export function compact(value: number): string {
  return compactFormat.format(value)
}

export function integer(value: number): string {
  return value.toLocaleString('en')
}

/** Signed difference in average placement, e.g. "-0.35". Negative is better. */
export function placementDelta(delta: number): string {
  if (Math.abs(delta) < 0.005) return '0.00'
  return `${delta > 0 ? '+' : '-'}${Math.abs(delta).toFixed(2)}`
}

export function timeAgo(ms: number, now = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - ms) / 60_000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}
