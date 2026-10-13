import type { EntityMatcher } from './entity-matcher'

// Minimal mdast shapes: enough to walk the tree without pulling in the unist types
interface Node {
  type: string
  value?: string
  children?: Node[]
  data?: unknown
}

const SKIP = new Set(['link', 'linkReference', 'code'])

function entityNode(match: NonNullable<ReturnType<EntityMatcher['lookup']>>): Node {
  return {
    type: 'tftEntity',
    data: { hName: 'tft-entity', hProperties: { kind: match.kind, api: match.ref.apiName } },
  }
}

/**
 * Remark plugin: replaces known unit, item and trait names in text (and in inline code that is
 * nothing but a name) with `<tft-entity kind api>` elements for the renderer to show as icons.
 */
export function remarkEntities(matcher: EntityMatcher) {
  const walk = (node: Node) => {
    if (!node.children || SKIP.has(node.type)) return
    const next: Node[] = []
    for (const child of node.children) {
      if (child.type === 'text' && child.value) {
        for (const part of matcher.split(child.value)) {
          next.push(typeof part === 'string' ? { type: 'text', value: part } : entityNode(part))
        }
      } else if (child.type === 'inlineCode' && child.value) {
        const match = matcher.lookup(child.value.trim())
        next.push(match ? entityNode(match) : child)
      } else {
        walk(child)
        next.push(child)
      }
    }
    node.children = next
  }
  return (tree: Node) => walk(tree)
}
