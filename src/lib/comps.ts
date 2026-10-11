import type { CompCategory } from '@/data/types'

export const CATEGORY_LABELS: Record<CompCategory, string> = {
  '1_cost_reroll': '1-cost reroll',
  '2_cost_reroll': '2-cost reroll',
  '3_cost_reroll': '3-cost reroll',
  fast_8: 'Fast 8',
  fast_9: 'Fast 9',
}

export const CATEGORY_IDS = Object.keys(CATEGORY_LABELS) as [CompCategory, ...CompCategory[]]

export function categoryLabel(category: CompCategory | null): string {
  return category ? CATEGORY_LABELS[category] : 'Uncategorized'
}
