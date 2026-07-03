import Link from 'next/link'
import {
  ArrowDownRight,
  ArrowUpRight,
  KeyRound,
  Lock,
  MessagesSquare,
  Plug,
  ShieldCheck,
  TerminalSquare,
} from 'lucide-react'
import { McpExamples } from '@/components/marketing/mcp-examples'
import { PricingCards } from '@/components/marketing/pricing-cards'
import { QuestionAnswerDemo } from '@/components/marketing/question-answer-demo'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const works = [
  'PostgreSQL',
  'ChatGPT',
  'Cursor',
  'VS Code',
  'Claude Desktop',
  'HTTP MCP',
]

const steps = [
  {
    n: '01',
    icon: Plug,
    title: 'Connect a database',
    body:
      'Use guided Postgres setup, or paste a connection string. PlainQuery validates it, blocks unsafe URLs, and stores the credential encrypted.',
  },
  {
    n: '02',
    icon: KeyRound,
    title: 'Pair an MCP client',
    body:
      'Guided setup for ChatGPT, Cursor, VS Code, Claude Desktop, or any HTTP MCP client. Drop in an API key — done.',
  },
  {
    n: '03',
    icon: MessagesSquare,
    title: 'Ask in plain English',
    body:
      'Revenue, retention, schema, churn — ask in a sentence. Read-only SQL is generated, validated, executed, and returned as a structured answer.',
  },
]

const trust = [
  {
    icon: ShieldCheck,
    title: 'Read-only by default',
    body: 'Every generated statement is parsed and rejected if it tries to write, drop, or call a dangerous function.',
  },
  {
    icon: Lock,
    title: 'Credentials encrypted at rest',
    body: 'Database URLs and LLM keys are sealed with Fernet keys you control. Rotate any time without downtime.',
  },
  {
    icon: TerminalSquare,
    title: 'Audited, capped, observable',
    body: 'A 100-row cap, 30-second timeout, and full query history per user — visible in the dashboard.',
  },
]

export default function HomePage() {
  return (
    <main>
      {/* ─────────────────────────  HERO  ───────────────────────── */}
      <section className="relative overflow-hidden border-b border-border">
        {/* Subtle dot grid + atmospheric blurs */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-dotgrid opacity-[0.55]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -top-40 left-1/3 h-[42rem] w-[42rem] -translate-x-1/2 rounded-full bg-primary/15 opacity-70 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-40 right-[-8rem] h-[28rem] w-[28rem] rounded-full bg-[oklch(0.92_0.13_92)]/35 blur-3xl"
        />

        <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-4 pb-20 pt-16 sm:px-6 lg:grid-cols-12 lg:gap-10 lg:pb-28 lg:pt-24 lg:px-8">
          {/* Left — copy column */}
          <div className="lg:col-span-7 xl:col-span-6">
            <div className="animate-fade-up flex items-center gap-3">
              <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-[11px] font-medium text-foreground shadow-sm">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-70 animate-ping" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                </span>
                <span className="font-mono uppercase tracking-[0.14em]">
                  v0.4 · public beta
                </span>
              </span>
              <span className="rule hidden flex-1 sm:block" />
              <span className="hidden font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground sm:inline">
                MCP server
              </span>
            </div>

            <h1 className="animate-fade-up delay-100 mt-8 font-display text-balance text-[3rem] font-semibold leading-[1.04] -tracking-[0.035em] sm:text-[3.9rem] lg:text-[4.6rem]">
              Ask your database{' '}
              <span className="text-primary">in plain English</span>
              <span className="text-primary">.</span>{' '}
              <span className="text-muted-foreground/85 font-normal">
                No SQL. No queue.
              </span>
            </h1>

            <p className="animate-fade-up delay-200 mt-7 max-w-xl text-lg leading-8 text-muted-foreground text-pretty">
              PlainQuery turns your Postgres database into something
              anyone on your team can talk to. Connect once, then ask
              questions from <span className="font-medium text-foreground">ChatGPT</span>,{' '}
              <span className="font-medium text-foreground">Cursor</span>, or{' '}
              <span className="font-medium text-foreground">VS Code</span> — answers
              come back as structured data.
            </p>

            <div className="animate-fade-up delay-300 mt-9 flex flex-wrap items-center gap-3">
              <Link
                href="/signup"
                className={cn(buttonVariants({ size: 'lg' }), 'h-12 px-6 group')}
              >
                Start free
                <ArrowUpRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
              </Link>
              <Link
                href="#examples"
                className={cn(
                  buttonVariants({ variant: 'outline', size: 'lg' }),
                  'h-12 px-6 bg-card backdrop-blur',
                )}
              >
                See it ask, generate, answer
                <ArrowDownRight className="h-4 w-4" />
              </Link>
            </div>

            <div className="animate-fade-up delay-500 mt-10 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
              <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em]">
                <Check2 /> 25 queries/day, free forever
              </span>
              <span className="hidden h-4 w-px bg-border sm:block" />
              <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em]">
                <Check2 /> no credit card
              </span>
              <span className="hidden h-4 w-px bg-border sm:block" />
              <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em]">
                <Check2 /> open-source MCP server
              </span>
            </div>
          </div>

          {/* Right — demo column */}
          <div className="relative lg:col-span-5 xl:col-span-6">
            <div className="relative mx-auto max-w-xl lg:ml-auto lg:max-w-none">
              <div
                aria-hidden
                className="absolute -inset-4 -z-10 rounded-[2rem] bg-foreground/[0.04] rotate-[1.4deg]"
              />
              <QuestionAnswerDemo className="animate-soft-pulse" />

              {/* Floating annotation */}
              <div className="hidden md:block absolute -bottom-7 -left-7 rounded-2xl border bg-card px-4 py-3 shadow-lg">
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                  03 · answer
                </p>
                <p className="mt-1 font-display text-base font-semibold -tracking-[0.02em]">
                  142 ms · validated
                </p>
              </div>

              {/* Floating tag, top-right */}
              <div className="hidden lg:flex absolute -top-5 -right-3 items-center gap-2 rounded-full border bg-card px-3 py-1.5 shadow-md">
                <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-foreground">
                  ask_database()
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Marquee strip */}
        <div className="relative border-t border-border bg-card/70">
          <div className="mx-auto flex max-w-7xl items-center gap-6 overflow-hidden px-4 py-5 sm:px-6 lg:px-8">
            <span className="eyebrow shrink-0 text-muted-foreground">
              Works with
            </span>
            <div className="flex w-full overflow-hidden mask-fade">
              <div className="flex shrink-0 animate-marquee gap-3 pr-3">
                {[...works, ...works].map((label, i) => (
                  <span
                    key={`${label}-${i}`}
                    className="shrink-0 rounded-full border border-border bg-background px-3.5 py-1.5 text-sm font-medium"
                  >
                    {label}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────  HOW IT WORKS  ───────────────────────── */}
      <section
        id="how-it-works"
        className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8"
      >
        <SectionHeader
          eyebrow="how it works"
          title={
            <>
              From <Underlined>database</Underlined> to{' '}
              <Underlined>answer</Underlined> in three calm steps.
            </>
          }
          intro="No new dialect, no new IDE. Connect, pair a client you already use, and start asking."
        />

        <div className="mt-14 grid gap-px overflow-hidden rounded-3xl border bg-border lg:grid-cols-3">
          {steps.map((step) => (
            <div
              key={step.n}
              className="group relative flex flex-col bg-card p-8 transition-colors hover:bg-card"
            >
              <div className="flex items-baseline justify-between">
                <span className="font-display text-4xl font-semibold -tracking-[0.04em] text-primary">
                  {step.n}
                </span>
                <step.icon className="h-5 w-5 text-muted-foreground transition-colors group-hover:text-primary" />
              </div>
              <h3 className="mt-8 font-display text-xl font-semibold -tracking-[0.02em]">
                {step.title}
              </h3>
              <p className="mt-3 text-sm leading-7 text-muted-foreground text-pretty">
                {step.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ─────────────────────────  EXAMPLES  ───────────────────────── */}
      <section
        id="examples"
        className="border-y border-border bg-muted/40"
      >
        <div className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8">
          <SectionHeader
            eyebrow="the ask_database tool"
            title={
              <>
                One MCP tool. <Highlighted>Three honest examples</Highlighted>
                <span className="text-primary">.</span>
              </>
            }
            intro="Below are real prompts your team would type into Cursor or ChatGPT. PlainQuery introspects the schema, generates SQL, validates it read-only, runs it under a row-cap, and returns a structured answer."
          />

          <div className="mt-14">
            <McpExamples />
          </div>

          <div className="mt-16 flex flex-col items-start gap-3 rounded-2xl border border-dashed border-foreground/15 bg-card p-6 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground text-pretty">
              Bad SQL? PlainQuery feeds the error back to the model and retries up to three times before giving up — so your teammates see a sentence, not a stack trace.
            </p>
            <Link
              href="/signup"
              className={cn(
                buttonVariants({ variant: 'default', size: 'sm' }),
                'shrink-0',
              )}
            >
              Try a real query
              <ArrowUpRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* ─────────────────────────  SECURITY  ───────────────────────── */}
      <section id="security" className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8">
        <div className="grid gap-14 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <SectionHeader
              eyebrow="built for trust"
              title={
                <>
                  A friendly product surface on top of a{' '}
                  <Underlined>guarded query engine</Underlined>.
                </>
              }
              intro="PlainQuery is designed for self-serve access without turning your database into a free-for-all. Every layer between the question and the data is auditable."
              align="left"
            />
            <Link
              href="#examples"
              className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline underline-offset-4"
            >
              See the validation pipeline
              <ArrowUpRight className="h-4 w-4" />
            </Link>
          </div>

          <div className="lg:col-span-7">
            <ul className="grid gap-px overflow-hidden rounded-3xl border bg-border sm:grid-cols-2">
              {trust.map((item, i) => (
                <li
                  key={item.title}
                  className={cn(
                    'flex flex-col bg-card p-7',
                    i === trust.length - 1 && 'sm:col-span-2 sm:flex-row sm:items-start sm:gap-6',
                  )}
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <item.icon className="h-5 w-5" />
                  </span>
                  <div className={cn('mt-5', i === trust.length - 1 && 'sm:mt-0')}>
                    <h3 className="font-display text-lg font-semibold -tracking-[0.02em]">
                      {item.title}
                    </h3>
                    <p className="mt-2 text-sm leading-7 text-muted-foreground text-pretty">
                      {item.body}
                    </p>
                  </div>
                </li>
              ))}
              <li className="relative flex flex-col justify-between bg-foreground p-7 text-background sm:col-span-2">
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 bg-dotgrid opacity-[0.18]"
                />
                <p className="relative font-mono text-[11px] uppercase tracking-[0.18em] text-background/55">
                  Threat model
                </p>
                <p className="relative mt-3 max-w-xl font-display text-2xl font-semibold leading-snug -tracking-[0.025em]">
                  “The agent should never be the reason a write happens.{' '}
                  <span className="text-primary">Ever.</span>”
                </p>
                <p className="relative mt-3 text-sm text-background/70">
                  Six layers of validation block DML/DDL, dangerous functions, multi-statement injection, and SSRF on user-supplied URLs.
                </p>
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* ─────────────────────────  PRICING  ───────────────────────── */}
      <section
        id="pricing"
        className="border-y border-border bg-muted/40"
      >
        <div className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <SectionHeader
              eyebrow="pricing"
              title={
                <>
                  Start free.{' '}
                  <Highlighted>Upgrade when it sticks.</Highlighted>
                </>
              }
              intro="No card on file. No drip-fed quotas. Move to Pro the day PlainQuery becomes a habit — not before."
              align="left"
              className="max-w-2xl"
            />
            <Link
              href="/pricing"
              className="inline-flex shrink-0 items-center gap-2 self-start text-sm font-semibold text-primary md:self-end"
            >
              Full pricing details
              <ArrowUpRight className="h-4 w-4" />
            </Link>
          </div>
          <div className="mt-12">
            <PricingCards />
          </div>
        </div>
      </section>

      {/* ─────────────────────────  FINAL CTA  ───────────────────────── */}
      <section className="px-4 pb-24 pt-20 sm:px-6 lg:px-8">
        <div className="relative mx-auto max-w-7xl overflow-hidden rounded-[2rem] border border-foreground/95 bg-foreground p-10 text-background shadow-[0_40px_80px_-24px_rgba(15,23,41,0.45)] sm:p-14">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-dotgrid opacity-[0.14]"
          />
          <div
            aria-hidden
            className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-primary/40 blur-3xl"
          />
          <div
            aria-hidden
            className="pointer-events-none absolute -left-24 -bottom-32 h-72 w-72 rounded-full bg-[oklch(0.92_0.13_92)]/25 blur-3xl"
          />

          <div className="relative grid items-end gap-10 lg:grid-cols-[1.4fr_1fr]">
            <div>
              <p className="eyebrow text-background/55">the ask</p>
              <h2 className="mt-4 font-display text-4xl font-semibold leading-[1.05] -tracking-[0.03em] sm:text-5xl">
                Stop waiting for a report.
                <br />
                <span className="text-background/65 font-normal">
                  Ask the question now.
                </span>
              </h2>
              <p className="mt-5 max-w-xl text-base leading-7 text-background/75">
                Connect one database, configure your AI client, and let your
                team start exploring answers in plain English. The free plan
                ships with everything you need to test it on real data.
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <Link
                href="/signup"
                className={cn(
                  buttonVariants({ variant: 'secondary', size: 'lg' }),
                  'h-12 justify-between px-6',
                )}
              >
                Create your account
                <ArrowUpRight className="h-4 w-4" />
              </Link>
              <Link
                href="/login"
                className="inline-flex items-center justify-between rounded-md px-6 py-3 text-sm font-medium text-background/80 ring-1 ring-inset ring-background/20 transition-colors hover:text-background"
              >
                I already have an account
                <ArrowUpRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </main>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Small inline helpers — kept here because they're only used by the landing.

function Check2() {
  return (
    <span
      aria-hidden
      className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-primary/15 text-primary"
    >
      <svg viewBox="0 0 12 12" className="h-2 w-2 fill-none stroke-current stroke-[2]">
        <path d="M2 6.5l2.5 2.5L10 3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  )
}

function Underlined({ children }: { children: React.ReactNode }) {
  return <span className="text-primary">{children}</span>
}

function Highlighted({ children }: { children: React.ReactNode }) {
  return <span className="text-primary">{children}</span>
}

interface SectionHeaderProps {
  eyebrow: string
  title: React.ReactNode
  intro?: string
  align?: 'left' | 'center'
  className?: string
}

function SectionHeader({
  eyebrow,
  title,
  intro,
  align = 'left',
  className,
}: SectionHeaderProps) {
  return (
    <div
      className={cn(
        align === 'center' ? 'mx-auto max-w-3xl text-center' : 'max-w-3xl',
        className,
      )}
    >
      <div
        className={cn(
          'flex items-center gap-3',
          align === 'center' && 'justify-center',
        )}
      >
        <span className="eyebrow text-primary">{eyebrow}</span>
        <span className="rule h-px w-16 flex-none" />
      </div>
      <h2 className="mt-4 font-display text-balance text-3xl font-semibold leading-[1.08] -tracking-[0.03em] sm:text-[2.6rem] lg:text-[3rem]">
        {title}
      </h2>
      {intro && (
        <p className="mt-5 text-base leading-7 text-muted-foreground text-pretty">
          {intro}
        </p>
      )}
    </div>
  )
}
