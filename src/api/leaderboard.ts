import { createClient } from '@supabase/supabase-js'
import { Database } from '../types/database.types'
import { QueryResult, QueryData, QueryError } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.supabase_url!,
  process.env.supabase_key!,
)

const getLeaderboardQuery = supabase
    .from('player')
    .select('*')
    .eq('tier', 'CHALLENGER')
    .order('LP', { ascending: false })
    .limit(100);

type Player = QueryData<typeof getLeaderboardQuery>;

export async function getLeaderboard() {
    const { data, error } = await getLeaderboardQuery;
    if (error) throw error; 
    const leaderboard: Player = data;
    return leaderboard;
}