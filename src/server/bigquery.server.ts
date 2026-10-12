import '@tanstack/react-start/server-only'
import { BigQuery } from '@google-cloud/bigquery'

// Local runs use Application Default Credentials (`gcloud auth application-default login`).
// Never hand this the data-editor service account from .env: the web app only reads.
// Hosts without gcloud (Railway) set GOOGLE_CREDENTIALS_JSON to a read-only service account key.
const DATASET = process.env.BQ_DATASET ?? 'tft'
const LOCATION = process.env.BQ_LOCATION ?? 'us-central1'
const DEFAULT_MAX_BYTES = 500_000_000

let client: BigQuery | undefined

function projectId(): string {
  const id = process.env.GOOGLE_CLOUD_PROJECT || process.env.GCP_PROJECT_ID
  if (!id) throw new Error('Set GOOGLE_CLOUD_PROJECT to the project that holds the tft dataset')
  return id
}

function credentials(): object | undefined {
  const json = process.env.GOOGLE_CREDENTIALS_JSON
  if (!json) return undefined
  try {
    return JSON.parse(json)
  } catch {
    throw new Error('GOOGLE_CREDENTIALS_JSON is not valid JSON')
  }
}

function bq(): BigQuery {
  // JOB_CREATION_OPTIONAL lets short queries skip creating a job. Setting jobTimeoutMs
  // would silently turn it off, so no timeout is set here.
  return (client ??= new BigQuery({
    projectId: projectId(),
    credentials: credentials(),
    defaultJobCreationMode: 'JOB_CREATION_OPTIONAL',
  }))
}

/** A fully qualified, quoted table or view name in the dataset. */
export function table(name: string): string {
  return `\`${projectId()}.${DATASET}.${name}\``
}

export function timestamp(ms: number) {
  // A JS Date would be sent as a STRUCT, not a TIMESTAMP
  return BigQuery.timestamp(new Date(ms))
}

/** Label values may only hold lowercase letters, digits, dashes and underscores. */
function labelValue(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_-]/g, '-').slice(0, 63)
}

export interface QueryOptions {
  /** Short name of the caller, kept as a job label so costs can be traced */
  fn: string
  /** Billing cap in bytes: the query fails instead of costing more */
  maxBytes?: number
  /** Needed for NULL and empty-array parameters, whose type can't be inferred */
  types?: Record<string, string>
}

/**
 * Runs a parameterized query. Only ever pass user input as `params`, never in the SQL text.
 * Failures are logged here and rethrown without the SQL, so a client never sees it.
 */
export async function runQuery<T>(
  sql: string,
  params: Record<string, unknown> | undefined,
  { fn, maxBytes = DEFAULT_MAX_BYTES, types }: QueryOptions,
): Promise<T[]> {
  try {
    const [rows] = await bq().query({
      query: sql,
      params,
      types,
      location: LOCATION,
      maximumBytesBilled: String(maxBytes),
      labels: { app: 'clone-tools-web', fn: labelValue(fn) },
    })
    return rows as T[]
  } catch (error) {
    console.error(`BigQuery query failed (${fn}):`, error)
    throw new Error(`Could not load data (${fn})`)
  }
}
