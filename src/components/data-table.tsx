import type { ReactNode } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export type SortDir = 'asc' | 'desc'

export interface Column<T> {
  id: string
  header: ReactNode
  cell: (row: T) => ReactNode
  /** Makes the column sortable */
  sortValue?: (row: T) => number | string
  /** Direction of the first click. Defaults to descending for numbers, ascending for text. */
  firstDir?: SortDir
  align?: 'left' | 'right'
  className?: string
}

export interface SortState {
  id: string
  dir: SortDir
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  sort: SortState
  onSortChange: (sort: SortState) => void
  empty?: ReactNode
}

/** Sorts a copy of `rows` by the chosen column. Stable, and keeps nulls out of the comparison. */
export function sortRows<T>(rows: T[], columns: Column<T>[], sort: SortState): T[] {
  const column = columns.find((c) => c.id === sort.id)
  if (!column?.sortValue) return rows
  const value = column.sortValue
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const x = value(a)
    const y = value(b)
    if (typeof x === 'string' || typeof y === 'string') return String(x).localeCompare(String(y)) * sign
    return (x - y) * sign
  })
}

export function DataTable<T>({ columns, rows, rowKey, sort, onSortChange, empty }: DataTableProps<T>) {
  const sorted = sortRows(rows, columns, sort)

  function clickHeader(column: Column<T>) {
    if (!column.sortValue) return
    if (sort.id === column.id) {
      onSortChange({ id: column.id, dir: sort.dir === 'asc' ? 'desc' : 'asc' })
    } else {
      const sample = rows.length > 0 ? column.sortValue(rows[0]) : 0
      onSortChange({ id: column.id, dir: column.firstDir ?? (typeof sample === 'string' ? 'asc' : 'desc') })
    }
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column) => {
              const active = sort.id === column.id
              return (
                <TableHead
                  key={column.id}
                  aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                  className={cn(column.align === 'right' && 'text-right', column.className)}
                >
                  {column.sortValue ? (
                    <button
                      type="button"
                      onClick={() => clickHeader(column)}
                      className={cn(
                        'inline-flex items-center gap-1 hover:text-foreground',
                        column.align === 'right' && 'flex-row-reverse',
                        active ? 'text-foreground' : 'text-muted-foreground',
                      )}
                    >
                      {column.header}
                      {active && (sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                    </button>
                  ) : (
                    column.header
                  )}
                </TableHead>
              )
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="py-10 text-center text-muted-foreground">
                {empty ?? 'Nothing to show.'}
              </TableCell>
            </TableRow>
          ) : (
            sorted.map((row) => (
              <TableRow key={rowKey(row)}>
                {columns.map((column) => (
                  <TableCell
                    key={column.id}
                    className={cn('tabular-nums', column.align === 'right' && 'text-right', column.className)}
                  >
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
