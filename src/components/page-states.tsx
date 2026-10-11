import type { ReactNode } from 'react'
import { Link, useRouter } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export function PageHeader({
  title,
  description,
  children,
}: {
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground" suppressHydrationWarning>
            {description}
          </p>
        )}
      </div>
      {children}
    </div>
  )
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="rounded-lg border border-dashed p-10 text-center">
      <p className="font-medium">{title}</p>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
    </div>
  )
}

/** The router's default error component. Details stay in the server log. */
export function ErrorState({ error, reset }: { error: Error; reset?: () => void }) {
  const router = useRouter()
  return (
    <div className="mx-auto max-w-lg rounded-lg border border-destructive/40 p-8 text-center">
      <p className="font-medium">Something went wrong</p>
      <p className="mt-1 text-sm text-muted-foreground">{error.message || 'The data could not be loaded.'}</p>
      <Button
        className="mt-4"
        variant="outline"
        onClick={() => {
          reset?.()
          router.invalidate()
        }}
      >
        Try again
      </Button>
    </div>
  )
}

export function NotFoundState({
  title = 'Not found',
  description = 'That page does not exist.',
  backTo = '/compositions',
  backLabel = 'Back to compositions',
}: {
  title?: string
  description?: string
  backTo?: string
  backLabel?: string
}) {
  return (
    <div className="mx-auto max-w-lg rounded-lg border p-8 text-center">
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      <Button asChild className="mt-4" variant="outline">
        <Link to={backTo}>{backLabel}</Link>
      </Button>
    </div>
  )
}

export function PendingState() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <div className="space-y-2 pt-4">
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </div>
  )
}
