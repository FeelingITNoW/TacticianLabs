import { Link } from '@tanstack/react-router'
import type { Meta } from '@/data/types'
import { compact, timeAgo } from '@/lib/format'

const NAV = [
  { to: '/compositions', label: 'Comps' },
  { to: '/units', label: 'Units' },
  { to: '/items', label: 'Items' },
  { to: '/leaderboard', label: 'Leaderboard' },
  { to: '/explorer', label: 'Explorer' },
  { to: '/ask', label: 'Ask' },
] as const

export function SiteHeader({ meta }: { meta: Meta | null }) {
  return (
    <header className="border-b bg-card/60 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3">
        <Link to="/" className="text-lg font-semibold tracking-tight">
          Tactician Labs
        </Link>
        <nav className="flex flex-wrap gap-1 text-sm">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="rounded-md px-3 py-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              activeProps={{ className: 'bg-muted text-foreground' }}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <p className="ml-auto text-xs text-muted-foreground" suppressHydrationWarning>
          {meta ? (
            <>
              Patch {meta.patch} · {compact(meta.matches)} matches · updated {timeAgo(meta.lastPlayedAt)}
            </>
          ) : (
            'Data unavailable'
          )}
        </p>
      </div>
    </header>
  )
}
