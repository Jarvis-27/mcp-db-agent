import { CheckCircle2, Database, Table2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface QuestionAnswerDemoProps {
  className?: string
}

const rows: Array<[string, string, string]> = [
  ['Acme Health', '$48,920', '+18%'],
  ['Northstar Labs', '$37,440', '+11%'],
  ['BrightCart Co.', '$29,780', '+8%'],
]

export function QuestionAnswerDemo({ className }: QuestionAnswerDemoProps) {
  return (
    <div
      className={cn(
        'pointer-events-none select-none rounded-[1.6rem] border bg-card shadow-[0_30px_60px_-24px_rgba(15,23,41,0.22)] ring-1 ring-border/70',
        className,
      )}
      aria-hidden="true"
    >
      {/* Window chrome */}
      <div className="flex items-center justify-between border-b px-5 py-3">
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-primary/85" />
          <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/30" />
          <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/30" />
        </div>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          plainquery · session
        </span>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-emerald-200">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          live
        </span>
      </div>

      {/* Prompt */}
      <div className="px-5 pt-5">
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          You · 09:42
        </p>
        <p className="mt-2 font-display text-xl font-semibold leading-[1.2] -tracking-[0.02em] text-foreground">
          Which customers generated the most revenue last month?
        </p>
      </div>

      <div className="px-5 pt-4">
        <div className="rule" />
      </div>

      {/* Tool call + result */}
      <div className="grid gap-3 px-5 py-5 sm:grid-cols-[0.85fr_1.15fr]">
        <div className="rounded-xl bg-muted/60 p-4">
          <div className="mb-3 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            <Database className="h-3 w-3" />
            tool · ask_database
          </div>
          <div className="space-y-1.5">
            {['orders', 'customers', 'payments'].map((table) => (
              <div
                key={table}
                className="flex items-center justify-between rounded-lg bg-background px-2.5 py-1.5 text-[11px] ring-1 ring-border"
              >
                <span className="font-mono">{table}</span>
                <CheckCircle2 className="h-3 w-3 text-emerald-600" />
              </div>
            ))}
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border bg-background">
          <div className="grid grid-cols-[1.4fr_0.9fr_0.7fr] bg-muted/60 px-3 py-2 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            <span>Customer</span>
            <span className="text-right">Revenue</span>
            <span className="text-right">Δ</span>
          </div>
          <div className="divide-y">
            {rows.map(([customer, revenue, change], index) => (
              <div
                key={customer}
                className="grid grid-cols-[1.4fr_0.9fr_0.7fr] items-center px-3 py-2.5 text-[13px] animate-fade-up"
                style={{ animationDelay: `${180 + index * 120}ms` }}
              >
                <span className="font-medium">{customer}</span>
                <span className="text-right font-mono text-[12px] tabular-nums">{revenue}</span>
                <span className="text-right text-[11px] font-semibold text-emerald-700">{change}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer bar */}
      <div className="flex items-center justify-between border-t bg-muted/40 px-5 py-3 text-[11px]">
        <span className="inline-flex items-center gap-1.5 font-mono uppercase tracking-[0.14em] text-muted-foreground">
          <Table2 className="h-3 w-3" />
          3 rows · 142 ms
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2 py-0.5 font-mono uppercase tracking-[0.14em] text-primary">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          read-only
        </span>
      </div>
    </div>
  )
}
