import { ArrowDownRight, Database, Sparkles, Table2, Terminal } from 'lucide-react'
import { cn } from '@/lib/utils'

type ResultColumn = { key: string; label: string; mono?: boolean; align?: 'left' | 'right' }
type ResultRow = Record<string, string>

interface Example {
  number: string
  badge: string
  prompt: string
  rationale: string
  sql: string
  columns: ResultColumn[]
  rows: ResultRow[]
}

const examples: Example[] = [
  {
    number: '01',
    badge: 'Revenue · last 30 days',
    prompt: 'Which five customers spent the most in the last 30 days?',
    rationale:
      'PlainQuery joined orders and customers, filtered by created_at, summed totals, and ranked descending. The query was validated read-only before it ran.',
    sql: `SELECT c.name, SUM(o.total) AS revenue
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE o.created_at >= NOW() - INTERVAL '30 days'
GROUP BY c.name
ORDER BY revenue DESC
LIMIT 5;`,
    columns: [
      { key: 'name', label: 'Customer' },
      { key: 'revenue', label: 'Revenue', mono: true, align: 'right' },
      { key: 'orders', label: 'Orders', mono: true, align: 'right' },
    ],
    rows: [
      { name: 'Acme Health', revenue: '$48,920', orders: '142' },
      { name: 'Northstar Labs', revenue: '$37,440', orders: '108' },
      { name: 'BrightCart Co.', revenue: '$29,780', orders: '94' },
      { name: 'Lumen Studio', revenue: '$22,114', orders: '71' },
      { name: 'Verdant Foods', revenue: '$18,902', orders: '63' },
    ],
  },
  {
    number: '02',
    badge: 'Cohort · churn',
    prompt: 'How many users signed up in March still placed an order this month?',
    rationale:
      'A cohort retention question. The agent introspected schema, joined users to orders, and bucketed by signup month — no manual SQL needed.',
    sql: `WITH march AS (
  SELECT id FROM users
  WHERE date_trunc('month', created_at) = '2026-03-01'
)
SELECT COUNT(DISTINCT u.id) AS retained,
       (SELECT COUNT(*) FROM march) AS cohort_size
FROM march u
JOIN orders o ON o.user_id = u.id
WHERE date_trunc('month', o.created_at) = date_trunc('month', NOW());`,
    columns: [
      { key: 'metric', label: 'Metric' },
      { key: 'value', label: 'Value', mono: true, align: 'right' },
    ],
    rows: [
      { metric: 'March cohort size', value: '1,284' },
      { metric: 'Retained this month', value: '419' },
      { metric: 'Retention rate', value: '32.6 %' },
    ],
  },
  {
    number: '03',
    badge: 'Schema · introspection',
    prompt: 'What columns does the orders table have, and which ones are indexed?',
    rationale:
      'A schema question. PlainQuery reads catalogs directly so onboarding teammates can map a database without opening a client.',
    sql: `SELECT column_name, data_type,
       CASE WHEN i.indexname IS NOT NULL
            THEN '✓' ELSE '' END AS indexed
FROM information_schema.columns c
LEFT JOIN pg_indexes i
  ON i.tablename = c.table_name
 AND i.indexdef ILIKE '%' || c.column_name || '%'
WHERE c.table_name = 'orders';`,
    columns: [
      { key: 'column', label: 'Column', mono: true },
      { key: 'type', label: 'Type', mono: true },
      { key: 'indexed', label: 'Idx', align: 'right' },
    ],
    rows: [
      { column: 'id', type: 'uuid', indexed: '✓' },
      { column: 'customer_id', type: 'uuid', indexed: '✓' },
      { column: 'total', type: 'numeric(10,2)', indexed: '' },
      { column: 'status', type: 'text', indexed: '✓' },
      { column: 'created_at', type: 'timestamptz', indexed: '✓' },
    ],
  },
]

export function McpExamples() {
  return (
    <div className="space-y-10">
      {examples.map((ex, idx) => (
        <ExampleCard key={ex.number} example={ex} reverse={idx % 2 === 1} />
      ))}
    </div>
  )
}

function ExampleCard({ example, reverse }: { example: Example; reverse: boolean }) {
  return (
    <article
      className={cn(
        'grid gap-6 lg:grid-cols-12 lg:items-stretch',
      )}
    >
      {/* Prompt + commentary column */}
      <div className={cn('lg:col-span-5 flex flex-col', reverse && 'lg:order-2')}>
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-xs text-muted-foreground">{example.number}</span>
          <span className="rule flex-1" />
          <span className="eyebrow text-muted-foreground">{example.badge}</span>
        </div>

        <p className="mt-5 font-display text-2xl font-semibold leading-[1.2] -tracking-[0.025em] sm:text-[1.75rem]">
          <span className="text-primary">“</span>
          {example.prompt}
          <span className="text-primary">”</span>
        </p>

        <p className="mt-4 text-sm leading-7 text-muted-foreground text-pretty">
          {example.rationale}
        </p>

        <div className="mt-6 inline-flex items-center gap-2 self-start rounded-full border bg-card/60 px-3 py-1.5 text-xs font-medium">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span className="font-mono">ask_database</span>
          <span className="text-muted-foreground">tool · MCP</span>
        </div>
      </div>

      {/* SQL + result column */}
      <div className={cn('lg:col-span-7 flex flex-col gap-3', reverse && 'lg:order-1')}>
        <div className="overflow-hidden rounded-2xl border bg-foreground/[0.97] text-background shadow-lg shadow-foreground/5">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
            <div className="flex items-center gap-2 text-[11px] font-medium tracking-wider text-background/70">
              <Terminal className="h-3.5 w-3.5" />
              <span className="font-mono uppercase">generated.sql</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-background/30" />
              <span className="h-2 w-2 rounded-full bg-background/30" />
              <span className="h-2 w-2 rounded-full bg-primary" />
            </div>
          </div>
          <pre className="overflow-x-auto px-4 py-4 font-mono text-[12.5px] leading-[1.6] text-background/90">
            <code>{highlightSql(example.sql)}</code>
          </pre>
        </div>

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <ArrowDownRight className="h-3.5 w-3.5" />
          <span className="font-mono uppercase tracking-wider">result · validated, capped at 100 rows</span>
        </div>

        <div className="overflow-hidden rounded-2xl border bg-card">
          <div
            className="grid bg-muted/60 px-4 py-2.5 text-[11px] font-mono uppercase tracking-[0.14em] text-muted-foreground"
            style={{ gridTemplateColumns: gridCols(example.columns) }}
          >
            {example.columns.map((c) => (
              <span key={c.key} className={cn(c.align === 'right' && 'text-right')}>
                {c.label}
              </span>
            ))}
          </div>
          <div className="divide-y">
            {example.rows.map((row, i) => (
              <div
                key={i}
                className="grid px-4 py-3 text-sm"
                style={{ gridTemplateColumns: gridCols(example.columns) }}
              >
                {example.columns.map((c) => (
                  <span
                    key={c.key}
                    className={cn(
                      c.mono ? 'font-mono text-[12.5px]' : 'font-medium',
                      c.align === 'right' && 'text-right tabular-nums',
                      c.key === 'indexed' && 'text-emerald-700',
                    )}
                  >
                    {row[c.key]}
                  </span>
                ))}
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between gap-3 border-t bg-card/50 px-4 py-2.5 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5 font-mono uppercase tracking-wider">
              <Table2 className="h-3 w-3" />
              {example.rows.length} rows
            </span>
            <span className="inline-flex items-center gap-1.5 font-mono uppercase tracking-wider">
              <Database className="h-3 w-3" />
              read-only
            </span>
          </div>
        </div>
      </div>
    </article>
  )
}

function gridCols(cols: ResultColumn[]) {
  return cols
    .map((c, i) => (i === 0 ? '1.4fr' : c.align === 'right' ? '0.8fr' : '1fr'))
    .join(' ')
}

const SQL_KEYWORDS = new Set([
  'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'ON',
  'GROUP', 'BY', 'ORDER', 'LIMIT', 'AS', 'AND', 'OR', 'NOT', 'NULL',
  'WITH', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'COUNT', 'SUM', 'DISTINCT',
  'INTERVAL', 'NOW', 'DATE_TRUNC', 'ILIKE', 'IS', 'IN',
])

function highlightSql(sql: string) {
  const tokens = sql.split(/(\s+|[(),;])/)
  return tokens.map((tok, i) => {
    if (!tok) return null
    const upper = tok.toUpperCase()
    if (SQL_KEYWORDS.has(upper)) {
      return (
        <span key={i} className="text-primary/90">
          {tok}
        </span>
      )
    }
    if (/^'.*'$/.test(tok)) {
      return (
        <span key={i} className="text-emerald-300/90">
          {tok}
        </span>
      )
    }
    if (/^[0-9]+(\.[0-9]+)?$/.test(tok)) {
      return (
        <span key={i} className="text-amber-300/90">
          {tok}
        </span>
      )
    }
    return <span key={i}>{tok}</span>
  })
}
