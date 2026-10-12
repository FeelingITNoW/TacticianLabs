// Production entry: serves the Vite build (dist/client) and the TanStack Start handler
// (dist/server/server.js). `npm run build` first, then `npm start`.
import { serve } from 'srvx'
import { serveStatic } from 'srvx/static'
import app from './dist/server/server.js'

const port = Number(process.env.PORT ?? 3000)

serve({
  port,
  hostname: '0.0.0.0',
  middleware: [
    // Railway's health check: answers without touching BigQuery
    (req, next) => (new URL(req.url).pathname === '/healthz' ? new Response('ok') : next()),
    async (req, next) => {
      const response = await next()
      // Built files carry a content hash in their name, so they never change
      if (new URL(req.url).pathname.startsWith('/assets/') && response.ok) {
        const headers = new Headers(response.headers)
        headers.set('cache-control', 'public, max-age=31536000, immutable')
        return new Response(response.body, { status: response.status, headers })
      }
      return response
    },
    serveStatic({ dir: 'dist/client' }),
  ],
  fetch: app.fetch,
})
