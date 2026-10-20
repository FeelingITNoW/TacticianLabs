import { useEffect, useRef, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Send } from 'lucide-react'
import { askAgentFn } from '@/data/agent.functions'
import { getCompsFn, getVariantsFn } from '@/data/compositions.functions'
import { getReferenceListsFn } from '@/data/meta.functions'
import type { AgentAnswer, AgentTurn } from '@/data/types'
import { AgentMarkdown } from '@/components/agent-markdown'
import { PageHeader } from '@/components/page-states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/ask')({
  loader: async () => {
    // Comps are optional: without them the answers still render, with comp links as plain text
    const [reference, comps, variants] = await Promise.all([
      getReferenceListsFn(),
      getCompsFn().catch(() => []),
      getVariantsFn().catch(() => []),
    ])
    return { reference, comps, variants }
  },
  head: () => ({ meta: [{ title: 'Ask · Tactician Labs' }] }),
  component: AskPage,
})

const EXAMPLES = [
  'Which champions have the best top 4 rate?',
  'What are the best 3 item builds on Taric?',
  "Which item matters most on Kha'Zix?",
  'What are the strongest 3-cost reroll comps?',
]

// How many earlier turns go along with a question (matches MAX_HISTORY_TURNS in the agent)
const HISTORY_TURNS = 6

interface Exchange {
  id: number
  question: string
  answer?: AgentAnswer
  error?: string
}

function Pending() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [])
  return (
    <div className="space-y-2" role="status" aria-live="polite">
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-24 w-full" />
      <p className="text-xs text-muted-foreground">Querying the stats… {seconds}s</p>
    </div>
  )
}

function AskPage() {
  const { reference, comps, variants } = Route.useLoaderData()
  const [thread, setThread] = useState<Exchange[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const nextId = useRef(0)
  // Names the thread in the agent's conversation log; a new chat gets a new one
  const conversationId = useRef<string>(undefined)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [thread])

  const send = async (question: string, earlier: Exchange[]) => {
    question = question.trim()
    if (!question || busy) return
    const id = nextId.current++
    conversationId.current ??= crypto.randomUUID()
    const history: AgentTurn[] = earlier
      .filter((e) => e.answer)
      .flatMap<AgentTurn>((e) => [
        { role: 'user', text: e.question },
        { role: 'model', text: e.answer!.text },
      ])
      .slice(-HISTORY_TURNS)
    setThread([...earlier, { id, question }])
    setDraft('')
    setBusy(true)
    try {
      const answer = await askAgentFn({ data: { question, history, conversation_id: conversationId.current } })
      setThread((t) => t.map((e) => (e.id === id ? { ...e, answer } : e)))
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : 'The agent failed to answer'
      setThread((t) => t.map((e) => (e.id === id ? { ...e, error: message } : e)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Ask the data"
        description="Ask a question in plain English. Answers come from the latest patch's ranked stats."
      >
        {thread.length > 0 && (
          <Button variant="outline" size="sm" disabled={busy} onClick={() => {
              conversationId.current = undefined
              setThread([])
            }}>
            New chat
          </Button>
        )}
      </PageHeader>

      {thread.length === 0 ? (
        <div className="mb-6 rounded-lg border border-dashed p-6">
          <p className="mb-3 text-sm text-muted-foreground">Try one of these:</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((q) => (
              <Button key={q} variant="outline" size="sm" onClick={() => send(q, [])}>
                {q}
              </Button>
            ))}
          </div>
        </div>
      ) : (
        <div className="mb-6 space-y-6">
          {thread.map((exchange, index) => (
            <div key={exchange.id} className="space-y-3">
              <div className="ml-auto w-fit max-w-[85%] rounded-lg bg-muted px-3 py-2 text-sm">{exchange.question}</div>
              <div className="rounded-lg border p-4">
                {exchange.answer ? (
                  <>
                    <AgentMarkdown text={exchange.answer.text} reference={reference} comps={comps} variants={variants} />
                    {exchange.answer.queries.length > 0 && (
                      <details className="mt-3 text-xs">
                        <summary className="cursor-pointer text-muted-foreground">
                          SQL ({exchange.answer.queries.length})
                        </summary>
                        {exchange.answer.queries.map((sql, i) => (
                          <pre key={i} className="mt-2 overflow-x-auto rounded-md bg-muted p-3">
                            {sql.trim()}
                          </pre>
                        ))}
                      </details>
                    )}
                  </>
                ) : exchange.error ? (
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <span className="text-destructive">{exchange.error}</span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => send(exchange.question, thread.slice(0, index))}
                    >
                      Retry
                    </Button>
                  </div>
                ) : (
                  <Pending />
                )}
              </div>
            </div>
          ))}
          <div ref={bottom} />
        </div>
      )}

      <p className="mb-2 text-center text-xs text-muted-foreground">
        Questions and answers are logged to improve the agent.
      </p>

      <form
        className="sticky bottom-4 flex items-end gap-2 rounded-lg border bg-card p-2 shadow-sm"
        onSubmit={(e) => {
          e.preventDefault()
          send(draft, thread)
        }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send(draft, thread)
            }
          }}
          maxLength={500}
          rows={2}
          disabled={busy}
          placeholder="e.g. What's the best build on Sivir?"
          aria-label="Your question"
          className="min-h-10 flex-1 resize-none rounded-md bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
        />
        <Button type="submit" disabled={busy || !draft.trim()}>
          <Send size={16} /> Send
        </Button>
      </form>
    </>
  )
}
