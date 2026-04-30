import { CheckCircle2, Database, MessageSquareText, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

interface QuestionAnswerDemoProps {
  className?: string
}

const rows = [
  ['Acme Health', '$48,920', '+18%'],
  ['Northstar Labs', '$37,440', '+11%'],
  ['BrightCart', '$29,780', '+8%'],
]

export function QuestionAnswerDemo({ className }: QuestionAnswerDemoProps) {
  return (
    <div
      className={cn(
        'pointer-events-none select-none rounded-[2rem] border bg-card/95 p-4 shadow-2xl shadow-primary/10 ring-1 ring-border/70',
        className,
      )}
      aria-hidden="true"
    >
      <div className="flex items-center justify-between border-b pb-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <MessageSquareText className="h-4 w-4" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Plain-English question
            </p>
            <p className="mt-1 text-sm font-medium">
              Which customers generated the most revenue last month?
            </p>
          </div>
        </div>
        <span className="hidden items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200 sm:inline-flex">
          <Sparkles className="h-3 w-3" />
          Answered
        </span>
      </div>

      <div className="grid gap-3 py-4 sm:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-2xl bg-muted/70 p-4">
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            <Database className="h-3.5 w-3.5" />
            Connected data
          </div>
          <div className="space-y-2">
            {['orders', 'customers', 'payments'].map((table) => (
              <div key={table} className="flex items-center justify-between rounded-xl bg-background px-3 py-2 text-xs ring-1 ring-border">
                <span className="font-mono">{table}</span>
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
              </div>
            ))}
          </div>
        </div>

        <div className="overflow-hidden rounded-2xl border bg-background">
          <div className="grid grid-cols-[1.4fr_0.9fr_0.7fr] bg-muted/70 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            <span>Customer</span>
            <span>Revenue</span>
            <span>Change</span>
          </div>
          <div className="divide-y">
            {rows.map(([customer, revenue, change], index) => (
              <div
                key={customer}
                className="grid grid-cols-[1.4fr_0.9fr_0.7fr] px-3 py-3 text-sm animate-fade-up"
                style={{ animationDelay: `${180 + index * 120}ms` }}
              >
                <span className="font-medium">{customer}</span>
                <span className="font-mono text-xs">{revenue}</span>
                <span className="text-xs font-semibold text-emerald-600">{change}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-primary px-4 py-3 text-primary-foreground">
        <p className="text-sm font-medium">Ready for ChatGPT, Cursor, VS Code, and HTTP MCP.</p>
        <span className="rounded-full bg-white/15 px-3 py-1 text-xs font-semibold">
          No SQL required
        </span>
      </div>
    </div>
  )
}
