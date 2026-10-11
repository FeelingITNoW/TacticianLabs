import { createFileRoute, redirect } from '@tanstack/react-router'

// Compositions are the front page; there is nothing else to show at the root yet
export const Route = createFileRoute('/')({
  beforeLoad: () => {
    throw redirect({ to: '/compositions' })
  },
})
