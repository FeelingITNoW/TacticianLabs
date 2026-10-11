import { useState } from 'react'
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

interface GameIconProps {
  kind: IconKind
  image: string | null
  name: string
  /** Champion cost, for the border colour */
  cost?: number
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

export function GameIcon({ kind, image, name, cost, size = 36, className }: GameIconProps) {
  const [failed, setFailed] = useState(false)
  const src = failed ? null : iconUrl(image)
  const style = { width: size, height: size }

  return (
    <span
      title={name}
      style={style}
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden bg-zinc-800 text-[10px] font-semibold text-zinc-300',
        kind === 'champion' && 'rounded-md ring-2',
        kind === 'champion' && (COST_RING[cost ?? 0] ?? 'ring-zinc-600'),
        kind === 'item' && 'rounded-md',
        kind === 'trait' && 'rounded-full p-1.5',
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
          // Champion art is a wide splash: crop to the centred subject
          className={cn(
            'h-full w-full',
            kind === 'champion' ? 'object-cover object-center' : 'object-contain',
          )}
        />
      ) : (
        <span aria-label={name}>{initials(name)}</span>
      )}
    </span>
  )
}
