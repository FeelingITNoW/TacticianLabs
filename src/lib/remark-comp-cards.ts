// Minimal mdast shapes: enough to walk the tree without pulling in the unist types
interface Node {
  type: string
  url?: string
  children?: Node[]
  data?: unknown
}

const COMP_HREF = /^\/compositions\/([^/?#\s]+)(?:\?variant=([^&#\s]+))?$/

export interface CompLink {
  comp: string
  variant: string | null
}

/** The comp (and variant) a `/compositions/<id>[?variant=<id>]` link points at, or null. */
export function parseCompHref(href: string | undefined): CompLink | null {
  const match = href ? COMP_HREF.exec(href) : null
  return match ? { comp: decodeURIComponent(match[1]), variant: match[2] ? decodeURIComponent(match[2]) : null } : null
}

/** The link a paragraph holds when the link is all it holds, looking through bold and italics. */
function soleLink(node: Node): Node | null {
  if (node.children?.length !== 1) return null
  const child = node.children[0]
  if (child.type === 'link') return child
  if (child.type === 'strong' || child.type === 'emphasis') return soleLink(child)
  return null
}

/**
 * Remark plugin: a paragraph that is nothing but a link to a comp (the agent writes one on its
 * own line for each comp it discusses) becomes a `<tft-comp comp variant>` element for the
 * renderer to show as a card. Links inside a sentence stay links.
 */
export function remarkCompCards() {
  const walk = (node: Node) => {
    if (!node.children) return
    node.children = node.children.map((child) => {
      if (child.type === 'paragraph') {
        const link = soleLink(child)
        const target = link ? parseCompHref(link.url) : null
        if (target) {
          return {
            type: 'tftComp',
            data: {
              hName: 'tft-comp',
              hProperties: { comp: target.comp, ...(target.variant && { variant: target.variant }) },
            },
          }
        }
      }
      walk(child)
      return child
    })
  }
  return (tree: Node) => walk(tree)
}
