'use client'

import { useState } from 'react'
import { Database, Table2, Terminal } from 'lucide-react'
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
  const [activeIdx, setActiveIdx] = useState(0)
  const active = examples[activeIdx]

  return (
    <div>
      {/* Tab strip */}
      <div
        role="tablist"
        aria-label="Example questions"
        className="flex flex-wrap gap-2"
      >
        {examples.map((ex, i) => {
          const selected = i === activeIdx
          return (
            <button
              key={ex.number}
              role="tab"
              aria-selected={selected}
              onClick={() => setActiveIdx(i)}
              className={cn(
                'group inline-flex items-center gap-2.5 rounded-full border px-4 py-2 text-xs font-mono uppercase tracking-[0.12em] transition',
                selected
                  ? 'border-foreground bg-foreground text-background shadow-sm'
                  : 'border-border bg-card text-muted-foreground hover:border-foreground/40 hover:text-foreground',
              )}
            >
              <span className={cn('text-[10px]', selected ? 'text-background/60' : 'text-muted-foreground/70')}>
                {ex.number}
              </span>
              <span>{ex.badge}</span>
            </button>
          )
        })}
      </div>

      {/* Active example panel */}
      <article className="mt-8 overflow-hidden rounded-2xl border bg-card shadow-sm">
        {/* Prompt header */}
        <header className="border-b bg-gradient-to-b from-muted/40 to-transparent px-6 py-8 sm:px-10 sm:py-10">
          <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            you ask
          </p>
          <p className="mt-3 font-display text-2xl font-semibold leading-[1.25] -tracking-[0.025em] sm:text-[1.75rem]">
            <span className="text-primary">“</span>
            {active.prompt}
            <span className="text-primary">”</span>
          </p>
          <p className="mt-4 max-w-3xl text-sm leading-7 text-muted-foreground text-pretty">
            {active.rationale}
          </p>
        </header>

        {/* SQL + result split */}
        <div className="grid lg:grid-cols-2">
          {/* SQL */}
          <div className="border-b bg-foreground/[0.97] text-background lg:border-b-0 lg:border-r lg:border-white/10">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
              <div className="flex items-center gap-2 text-[11px] font-medium tracking-wider text-background/70">
                <Terminal className="h-3.5 w-3.5" />
                <span className="font-mono uppercase">generated.sql</span>
              </div>
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-background/45">
                validated · read-only
              </span>
            </div>
            <pre className="overflow-x-auto px-5 py-5 font-mono text-[12.5px] leading-[1.65] text-background/90">
              <code>{highlightSql(active.sql)}</code>
            </pre>
          </div>

          {/* Result */}
          <div className="flex flex-col">
            <div className="flex items-center justify-between border-b px-5 py-3">
              <div className="flex items-center gap-2 text-[11px] font-medium tracking-wider text-muted-foreground">
                <Table2 className="h-3.5 w-3.5" />
                <span className="font-mono uppercase">result</span>
              </div>
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                {active.rows.length} rows · capped at 100
              </span>
            </div>

            <div
              className="grid bg-muted/50 px-5 py-2.5 text-[11px] font-mono uppercase tracking-[0.14em] text-muted-foreground"
              style={{ gridTemplateColumns: gridCols(active.columns) }}
            >
              {active.columns.map((c) => (
                <span key={c.key} className={cn(c.align === 'right' && 'text-right')}>
                  {c.label}
                </span>
              ))}
            </div>
            <div className="divide-y">
              {active.rows.map((row, i) => (
                <div
                  key={i}
                  className="grid px-5 py-3 text-sm"
                  style={{ gridTemplateColumns: gridCols(active.columns) }}
                >
                  {active.columns.map((c) => (
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

            <div className="mt-auto flex items-center gap-2 border-t bg-card/40 px-5 py-2.5 text-[11px] text-muted-foreground">
              <Database className="h-3 w-3" />
              <span className="font-mono uppercase tracking-wider">
                ask_database · MCP tool
              </span>
            </div>
          </div>
        </div>
      </article>
    </div>
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
