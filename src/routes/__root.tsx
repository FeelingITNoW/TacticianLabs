// src/routes/__root.tsx
/// <reference types="vite/client" />
import type { ReactNode } from 'react'
import {
  Outlet,
  createRootRoute,
  HeadContent,
  Scripts,
} from '@tanstack/react-router'
import appCss from '../styles/app.css?url'
import { getMetaFn } from '@/data/meta.functions'
import { SiteHeader } from '@/components/site-header'
import { TooltipProvider } from '@/components/ui/tooltip'
import { DDRAGON_ORIGIN } from '@/lib/ddragon'

export const Route = createRootRoute({
  head: () => ({
    meta: [
      {
        charSet: 'utf-8',
      },
      {
        name: 'viewport',
        content: 'width=device-width, initial-scale=1',
      },
      {
        title: 'Tactician Labs',
      },
    ],
    links: [
      { rel: 'stylesheet', href: appCss },
      // No icon yet; an empty one stops the browser asking for /favicon.ico on every page
      { rel: 'icon', href: 'data:,' },
      { rel: 'preconnect', href: DDRAGON_ORIGIN },
    ],
  }),
  // The header shows the patch. If the data can't be read the pages say so themselves.
  loader: () => getMetaFn().catch(() => null),
  staleTime: 10 * 60_000,
  component: RootComponent,
})

function RootComponent() {
  return (
    <RootDocument>
      <Shell />
    </RootDocument>
  )
}

function Shell() {
  const meta = Route.useLoaderData()
  return (
    <>
      <SiteHeader meta={meta} />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-muted-foreground">
        Tactician Labs isn&apos;t endorsed by Riot Games and doesn&apos;t reflect the views or opinions of Riot
        Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all
        associated properties are trademarks or registered trademarks of Riot Games, Inc.
      </footer>
    </>
  )
}

function RootDocument({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <head>
        <HeadContent />
      </head>
      <body className="min-h-screen antialiased">
        <TooltipProvider>{children}</TooltipProvider>
        <Scripts />
      </body>
    </html>
  )
}
