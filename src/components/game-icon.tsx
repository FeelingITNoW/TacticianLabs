import { useState } from 'react'
import type { TraitStyle } from '@/data/types'
import { iconUrl } from '@/lib/ddragon'
import { cn } from '@/lib/utils'

export type IconKind = 'champion' | 'item' | 'trait'

// Border colour by champion cost, as in the game
const COST_RING: Record<number, string> = {
  1: 'ring-zinc-400',
  2: 'ring-emerald-500',
  3: 'ring-sky-500',
  4: 'ring-fuchsia-500',
  5: 'ring-amber-400',
}

// Hexagon colour by trait style, as in the game; traits with no known style stay neutral
const TRAIT_HEX: Record<TraitStyle, string> = {
  bronze: 'bg-gradient-to-b from-amber-700 to-amber-900',
  silver: 'bg-gradient-to-b from-zinc-300 to-zinc-500',
  gold: 'bg-gradient-to-b from-yellow-300 to-amber-500',
  prismatic: 'bg-gradient-to-br from-fuchsia-300 via-sky-300 to-emerald-300',
  unique: 'bg-gradient-to-b from-violet-500 to-violet-800',
}
const HEXAGON = 'polygon(50% 0, 93% 25%, 93% 75%, 50% 100%, 7% 75%, 7% 25%)'
// The glyph is white; on the light styles it goes dark
const DARK_GLYPH = new Set<TraitStyle>(['gold', 'prismatic', 'silver'])

interface GameIconProps {
  kind: IconKind
  image: string | null
  name: string
  /** Champion cost, for the border colour */
  cost?: number
  /** Trait style, for the hexagon colour */
  style?: TraitStyle | null
  size?: number
  className?: string
}

function initials(name: string): string {
  return name
    .split(/[\s']+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join('')
}

export function GameIcon({ kind, image, name, cost, style: traitStyle, size = 36, className }: GameIconProps) {
  const [failed, setFailed] = useState(false)
  const src = failed ? null : iconUrl(image)
  const box = {
    width: size,
    height: size,
    ...(kind === 'trait' && { clipPath: HEXAGON }),
  }

  return (
    <span
      title={name}
      style={box}
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden bg-zinc-800 text-[10px] font-semibold text-zinc-300',
        kind === 'champion' && 'rounded-md ring-2',
        kind === 'champion' && (COST_RING[cost ?? 0] ?? 'ring-zinc-600'),
        kind === 'item' && 'rounded-md',
        kind === 'trait' && 'p-[18%]',
        kind === 'trait' && (traitStyle ? TRAIT_HEX[traitStyle] : 'bg-zinc-700'),
        className,
      )}
    >
      {src ? (
        <img
          src={src}
          alt={name}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className={cn(
            'h-full w-full',
            kind === 'champion' ? 'object-cover' : 'object-contain',
            kind === 'trait' && traitStyle && DARK_GLYPH.has(traitStyle) && 'invert',
          )}
        />
      ) : (
        <span aria-label={name}>{initials(name)}</span>
      )}
    </span>
  )
}
