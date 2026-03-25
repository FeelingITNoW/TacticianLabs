import { createFileRoute } from '@tanstack/react-router'
import { getLeaderboard } from '../api/leaderboard'

export const Route = createFileRoute('/leaderboard')({
  component: RouteComponent,
  loader: () => getLeaderboard(),
})

function RouteComponent() {
  const leaderboardData = Route.useLoaderData()
  return (
    <div>
      {leaderboardData.map((player) => (
        <div key={player.uuid}>
          {player.player_name} - {player.LP} LP
        </div>
      ))}
    </div>
  )
}
