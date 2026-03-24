// src/routes/index.tsx
import * as fs from 'node:fs'
import { createClient } from '@supabase/supabase-js'
import { createFileRoute, useRouter } from '@tanstack/react-router'
import { createServerFn } from '@tanstack/react-start'

import { Database } from '../types/database.types'
import { Link } from '@tanstack/react-router'
import { QueryResult, QueryData, QueryError } from '@supabase/supabase-js'

const filePath = 'count.txt'

// Create a single supabase client for interacting with your database
const supabase = createClient(
  process.env.supabase_url!,
  process.env.supabase_key!,
)

const getTenCompositionsQuery = supabase
    .from('composition')
    .select('*')
    .limit(10);

type Composition = QueryData<typeof getTenCompositionsQuery>;

const { data, error } = await getTenCompositionsQuery;
if (error) throw error; 
const Compositions: Composition = data;

async function readCount() {
  return parseInt(
    await fs.promises.readFile(filePath, 'utf-8').catch(() => '0'),
  )
}

const getCount = createServerFn({
  method: 'GET',
}).handler(() => {
  return readCount()
})

const updateCount = createServerFn({ method: 'POST' })
  .inputValidator((d: number) => d)
  .handler(async ({ data }) => {
    const count = await readCount()
    await fs.promises.writeFile(filePath, `${count + data}`)
  })

export const Route = createFileRoute('/')({
  component: Home,
  loader: async () => await getCount(),
})

function Home() {
  const router = useRouter()
  const state = Route.useLoaderData()

  return (
    <>
    <h1>Hello World</h1>
    <button
      type="button"
      onClick={() => {
        updateCount({ data: 1 }).then(() => {
          router.invalidate()
        })
      }}
    >
      Add 1 to {state}?
    </button>
    <Link to="/leaderboard">Go to leaderboard</Link>
    <h3>Compositions: {JSON.stringify(Compositions)}</h3>
    </>
  )
}