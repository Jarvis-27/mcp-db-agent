import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight, HelpCircle } from 'lucide-react'
import { PricingCards } from '@/components/marketing/pricing-cards'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export const metadata: Metadata = {
  title: 'Pricing',
  description:
    'Start free with PlainQuery. Connect Postgres, ask database questions in plain English from MCP clients, and upgrade when your team needs more daily queries.',
  alternates: {
    canonical: '/pricing',
  },
}

const faqs = [
  {
    question: 'Do I need to know SQL?',
    answer:
      'No. PlainQuery is built for plain-English questions. The app generates and validates SQL behind the scenes.',
  },
  {
    question: 'Which databases are supported?',
    answer:
      'The hosted SaaS flow is designed for PostgreSQL databases.',
  },
  {
    question: 'How much is Pro?',
    answer:
      'Pro is $25/month, billed securely through Stripe. Signed-in users upgrade from the billing page once their workspace is ready.',
  },
  {
    question: 'Can I use ChatGPT, Cursor, VS Code, or Claude Desktop?',
    answer:
      'Yes. The app generates client-specific setup guidance for ChatGPT, Cursor, VS Code, Claude Desktop, and generic HTTP MCP clients.',
  },
]

export default function PricingPage() {
  return (
    <main>
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            Pricing
          </p>
          <h1 className="mt-4 text-balance text-5xl font-semibold tracking-tight sm:text-6xl">
            Clear limits while the product is young.
          </h1>
          <p className="mt-6 text-lg leading-8 text-muted-foreground">
            Start with 25 plain-English database questions per day. Pro keeps
            the same simple workflow and raises the ceiling when you need more.
          </p>
        </div>

        <div className="mt-12">
          <PricingCards />
        </div>
      </section>

      <section className="border-y bg-card/45">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="grid gap-5 md:grid-cols-2">
            {faqs.map((item) => (
              <div key={item.question} className="rounded-3xl bg-background p-6 shadow-sm ring-1 ring-border">
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                    <HelpCircle className="h-5 w-5" />
                  </span>
                  <h2 className="text-lg font-semibold">{item.question}</h2>
                </div>
                <p className="mt-4 text-sm leading-6 text-muted-foreground">{item.answer}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="rounded-[2rem] bg-primary p-8 text-primary-foreground shadow-xl shadow-primary/15 sm:p-10">
          <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-3xl font-semibold tracking-tight">Start with the free plan.</h2>
              <p className="mt-2 text-primary-foreground/80">
                Connect a database and see if plain-English answers change your workflow.
              </p>
            </div>
            <Link
              href="/signup"
              className={cn(buttonVariants({ variant: 'secondary', size: 'lg' }), 'h-11 px-5')}
            >
              Create account
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>
    </main>
  )
}
