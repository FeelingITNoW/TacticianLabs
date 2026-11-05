import type { RollOddsRun } from '@/data/types'
import { pct } from '@/lib/format'
import { describeRollOdds } from '@/lib/roll-odds'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/** One roll_odds call: what was asked, then the odds at each amount of gold */
export function RollOddsCard({ run }: { run: RollOddsRun }) {
  const names = run.units.map((unit) => unit.name)
  return (
    <div className="mt-2 space-y-2">
      <p>{describeRollOdds(run)}</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Gold</TableHead>
            <TableHead className="text-right">Rolls</TableHead>
            <TableHead className="text-right">All units</TableHead>
            {names.map((name) => (
              <TableHead key={name} className="text-right">
                {name}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {run.results.map((row) => (
            <TableRow key={row.gold}>
              <TableCell>{row.gold}</TableCell>
              <TableCell className="text-right tabular-nums">{row.rolls}</TableCell>
              <TableCell className="text-right font-medium tabular-nums">{pct(row.allUnits)}</TableCell>
              {names.map((name) => (
                <TableCell key={name} className="text-right tabular-nums">
                  {pct(row.perUnit[name] ?? 0)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
