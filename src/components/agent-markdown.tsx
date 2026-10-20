import { useMemo, type ComponentProps, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { CompRow, ReferenceLists, VariantRow } from '@/data/types'
import { buildEntityMatcher } from '@/lib/entity-matcher'
import { parseCompHref, remarkCompCards } from '@/lib/remark-comp-cards'
import { remarkEntities } from '@/lib/remark-entities'
import { cn } from '@/lib/utils'
import { CompCard } from '@/components/comp-card'
import { GameIcon } from '@/components/game-icon'
import { VariantCard } from '@/components/variant-card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type Kind = 'champion' | 'item' | 'trait'

const NUMERIC = /^[-+]?[\d,.]+%?$/

/** Text of a table cell's children, to right-align numbers */
function plainText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(plainText).join('')
  return ''
}

interface AgentMarkdownProps {
  text: string
  reference: ReferenceLists
  /** The latest patch's comps and variants: a comp the agent links to is only shown if it is here */
  comps: CompRow[]
  variants: VariantRow[]
}

export function AgentMarkdown({ text, reference, comps, variants }: AgentMarkdownProps) {
  const { matcher, components } = useMemo(() => {
    const compsById = new Map(comps.map((c) => [c.compId, c]))
    const variantsById = new Map(variants.map((v) => [v.variantId, v]))

    const matcher = buildEntityMatcher(reference)
    const champions = new Map(reference.champions.map((c) => [c.apiName, c]))
    const items = new Map(reference.items.map((i) => [i.apiName, i]))
    const traits = new Map(reference.traits.map((t) => [t.apiName, t]))

    const Entity = ({ kind, api }: { kind: Kind; api: string }) => {
      const ref = (kind === 'champion' ? champions : kind === 'item' ? items : traits).get(api)
      if (!ref) return <>{api}</>
      const inner = (
        <>
          <GameIcon
            kind={kind}
            image={ref.image}
            name={ref.name}
            cost={kind === 'champion' ? champions.get(api)?.cost : undefined}
            size={20}
          />
          <span>{ref.name}</span>
        </>
      )
      const cls = 'inline-flex items-center gap-1.5 align-middle font-medium whitespace-nowrap'
      return kind === 'champion' ? (
        <Link to="/units/$unitId" params={{ unitId: api }} search={{ tab: 'items' }} className={cn(cls, 'hover:underline')}>
          {inner}
        </Link>
      ) : (
        <span className={cls}>{inner}</span>
      )
    }

    // The agent can write an id from an older clustering or make one up: those show as plain text
    const CompView = ({ comp, variant }: { comp: string; variant?: string }) => {
      const variantRow = variant ? variantsById.get(variant) : undefined
      if (variantRow && variantRow.compId === comp) return <VariantCard variant={variantRow} />
      const compRow = compsById.get(comp)
      return compRow ? <CompCard comp={compRow} /> : null
    }

    const numeric = (children: ReactNode, align?: string | null) =>
      align === 'right' || (align == null && NUMERIC.test(plainText(children).trim()))

    const components = {
      'tft-entity': Entity,
      'tft-comp': CompView,
      p: (p: ComponentProps<'p'>) => <p className="my-2 leading-relaxed" {...p} />,
      ul: (p: ComponentProps<'ul'>) => <ul className="my-2 list-disc space-y-1 pl-5" {...p} />,
      ol: (p: ComponentProps<'ol'>) => <ol className="my-2 list-decimal space-y-1 pl-5" {...p} />,
      h1: (p: ComponentProps<'h1'>) => <h3 className="mt-4 mb-2 text-lg font-semibold" {...p} />,
      h2: (p: ComponentProps<'h2'>) => <h3 className="mt-4 mb-2 text-base font-semibold" {...p} />,
      h3: (p: ComponentProps<'h3'>) => <h3 className="mt-3 mb-1 text-sm font-semibold" {...p} />,
      strong: (p: ComponentProps<'strong'>) => <strong className="font-semibold" {...p} />,
      code: (p: ComponentProps<'code'>) => <code className="rounded bg-muted px-1 py-0.5 text-[0.85em]" {...p} />,
      pre: (p: ComponentProps<'pre'>) => (
        <pre className="my-2 overflow-x-auto rounded-md bg-muted p-3 text-xs [&_code]:bg-transparent [&_code]:p-0" {...p} />
      ),
      a: ({ href, children, ...rest }: ComponentProps<'a'>) => {
        const target = parseCompHref(href)
        if (!target) {
          return (
            <a className="underline underline-offset-2" target="_blank" rel="noreferrer noopener" href={href} {...rest}>
              {children}
            </a>
          )
        }
        const comp = compsById.get(target.comp)
        if (!comp) return <>{children}</>
        return (
          <Link to="/compositions/$compId" params={{ compId: comp.compId }} className="underline underline-offset-2">
            {children}
          </Link>
        )
      },
      table: ({ children }: ComponentProps<'table'>) => (
        <div className="my-3 overflow-x-auto rounded-lg border">
          <Table>{children}</Table>
        </div>
      ),
      thead: ({ children }: ComponentProps<'thead'>) => <TableHeader>{children}</TableHeader>,
      tbody: ({ children }: ComponentProps<'tbody'>) => <TableBody>{children}</TableBody>,
      tr: ({ children }: ComponentProps<'tr'>) => <TableRow>{children}</TableRow>,
      th: ({ children, style }: ComponentProps<'th'>) => (
        <TableHead className={cn(numeric(children, style?.textAlign as string | undefined) && 'text-right')}>
          {children}
        </TableHead>
      ),
      td: ({ children, style }: ComponentProps<'td'>) => (
        <TableCell
          className={cn(numeric(children, style?.textAlign as string | undefined) && 'text-right tabular-nums')}
        >
          {children}
        </TableCell>
      ),
    } as unknown as Components

    return { matcher, components }
  }, [reference, comps, variants])

  return (
    <div className="text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkCompCards, [remarkEntities, matcher]]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
