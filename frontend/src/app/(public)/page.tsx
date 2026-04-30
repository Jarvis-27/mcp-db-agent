import Link from 'next/link'
import {
  ArrowRight,
  CheckCircle2,
  Database,
  KeyRound,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { PricingCards } from '@/components/marketing/pricing-cards'
import { QuestionAnswerDemo } from '@/components/marketing/question-answer-demo'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const supported = ['PostgreSQL', 'MySQL', 'ChatGPT', 'Cursor', 'VS Code', 'HTTP MCP']

const steps = [
  {
    icon: Database,
    title: 'Connect your database',
    description:
      'Add a PostgreSQL or MySQL connection string. PlainQuery validates it and stores credentials encrypted.',
  },
  {
    icon: KeyRound,
    title: 'Connect your AI client',
    description:
      'Use guided setup for ChatGPT, Cursor, VS Code, or a generic HTTP MCP client.',
  },
  {
    icon: MessageSquareText,
    title: 'Ask normal questions',
    description:
      'Ask for customers, revenue, orders, churn, or schema details in everyday language.',
  },
]

const trust = [
  'Credentials encrypted at rest',
  'Read-only SQL validation before execution',
  'Daily quota and query history in the dashboard',
  'OAuth-first remote MCP support with API-key fallback',
]

export default function HomePage() {
  return (
    <main>
      <section className="relative overflow-hidden border-b">
        <div className="absolute inset-0">
          <div className="absolute right-[-6rem] top-16 hidden w-[58rem] rotate-[-2deg] opacity-95 lg:block">
            <QuestionAnswerDemo className="animate-soft-pulse" />
          </div>
          <div className="absolute inset-x-4 top-56 opacity-25 sm:top-48 lg:hidden">
            <QuestionAnswerDemo />
          </div>
        </div>

        <div className="relative mx-auto flex min-h-[78svh] max-w-7xl flex-col justify-center px-4 py-20 sm:px-6 lg:px-8">
          <div className="max-w-2xl">
            <div className="animate-fade-up inline-flex items-center gap-2 rounded-full border bg-card/90 px-3 py-1.5 text-sm font-medium shadow-sm">
              <Sparkles className="h-4 w-4 text-primary" />
              Answers from your database, without SQL
            </div>
            <h1 className="animate-fade-up delay-100 mt-7 text-balance text-5xl font-semibold tracking-tight text-foreground sm:text-6xl lg:text-7xl">
              Ask your database like you ask a teammate.
            </h1>
            <p className="animate-fade-up delay-200 mt-6 max-w-xl text-lg leading-8 text-muted-foreground">
              PlainQuery lets anyone get answers from company data in plain English,
              without writing SQL or waiting for a data specialist to pull a report.
            </p>
            <div className="animate-fade-up delay-300 mt-8 flex flex-col gap-3 sm:flex-row">
              <Link href="/signup" className={cn(buttonVariants({ size: 'lg' }), 'h-11 px-5')}>
                Start free
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="#how-it-works"
                className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-11 px-5 bg-background/70')}
              >
                See how it works
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="border-b bg-card/35">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-6 sm:px-6 lg:px-8">
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Works with
          </span>
          {supported.map((item) => (
            <span
              key={item}
              className="rounded-full border bg-background px-3 py-1.5 text-sm font-medium shadow-sm"
            >
              {item}
            </span>
          ))}
        </div>
      </section>

      <section id="how-it-works" className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            How it works
          </p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            From database to answer in three calm steps.
          </h2>
        </div>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {steps.map((step, index) => (
            <div
              key={step.title}
              className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-border transition-transform hover:-translate-y-1"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <step.icon className="h-5 w-5" />
              </span>
              <p className="mt-6 text-sm font-semibold text-muted-foreground">
                Step {index + 1}
              </p>
              <h3 className="mt-2 text-xl font-semibold">{step.title}</h3>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">{step.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="security" className="border-y bg-card/45">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[0.9fr_1.1fr] lg:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
              Built for trust
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
              A friendly product surface on top of a guarded query engine.
            </h2>
            <p className="mt-5 text-base leading-7 text-muted-foreground">
              PlainQuery is designed for self-serve access without turning your
              database into a free-for-all. The app validates database URLs, stores
              credentials encrypted, validates SQL, and keeps usage visible.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {trust.map((item) => (
              <div key={item} className="rounded-2xl bg-background p-5 shadow-sm ring-1 ring-border">
                <ShieldCheck className="h-5 w-5 text-emerald-600" />
                <p className="mt-4 text-sm font-medium">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="pricing" className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="mb-10 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
              Pricing
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
              Start free, upgrade when PlainQuery becomes a habit.
            </h2>
          </div>
          <Link href="/pricing" className="inline-flex items-center gap-2 text-sm font-semibold text-primary">
            View pricing details
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
        <PricingCards />
      </section>

      <section className="px-4 pb-20 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl rounded-[2rem] bg-primary p-8 text-primary-foreground shadow-xl shadow-primary/15 sm:p-10">
          <div className="grid gap-8 lg:grid-cols-[1fr_auto] lg:items-center">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1.5 text-sm font-medium">
                <CheckCircle2 className="h-4 w-4" />
                Free plan available
              </div>
              <h2 className="mt-5 text-3xl font-semibold tracking-tight sm:text-4xl">
                Stop waiting for a report. Ask the question now.
              </h2>
              <p className="mt-3 max-w-2xl text-primary-foreground/80">
                Connect one database, configure your AI client, and let your team
                start exploring answers in plain English.
              </p>
            </div>
            <Link
              href="/signup"
              className={cn(buttonVariants({ variant: 'secondary', size: 'lg' }), 'h-11 px-5')}
            >
              Create your account
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>
    </main>
  )
}
