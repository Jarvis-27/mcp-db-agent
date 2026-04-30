'use client'

import { useActionState } from 'react'
import Link from 'next/link'
import { ArrowRight, CheckCircle2, Mail, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { registerAction } from './actions'

type State = { success?: boolean; error?: string } | null

export default function SignupPage() {
  const [state, formAction, isPending] = useActionState<State, FormData>(
    registerAction,
    null,
  )

  return (
    <main className="mx-auto grid min-h-[calc(100vh-8rem)] max-w-6xl items-center gap-10 px-4 py-12 sm:px-6 lg:grid-cols-[1fr_0.9fr] lg:px-8">
      <section className="max-w-xl">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          Start free
        </p>
        <h1 className="mt-4 text-balance text-4xl font-semibold tracking-tight sm:text-5xl">
          Give everyone a direct line to database answers.
        </h1>
        <p className="mt-5 text-base leading-7 text-muted-foreground">
          Create an account, verify your email, connect one database, and copy
          guided setup for your AI client.
        </p>
        <div className="mt-8 grid gap-3 text-sm">
          {[
            '25 plain-English database questions per day',
            'No credit card required for the free plan',
            'Credentials encrypted and never shown back to the browser',
          ].map((item) => (
            <div key={item} className="flex items-center gap-3">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              <span>{item}</span>
            </div>
          ))}
        </div>
      </section>

      {state?.success ? (
        <Card className="rounded-3xl shadow-xl shadow-primary/10">
          <CardHeader>
            <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
              <Mail className="h-5 w-5" />
            </div>
            <CardTitle className="text-2xl">Check your email</CardTitle>
            <CardDescription className="text-base leading-7">
              We sent a verification link to your address. Click it to continue
              setting up your database connection.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-muted-foreground">
              The link expires in 60 minutes. If you do not see it, check your
              spam folder.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card className="rounded-3xl shadow-xl shadow-primary/10">
          <CardHeader>
            <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <CardTitle className="text-2xl">Create your account</CardTitle>
            <CardDescription className="text-base leading-7">
              Start with the free plan and connect your first database after email verification.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form action={formAction} className="space-y-4">
              {state?.error && (
                <Alert variant="destructive">
                  <AlertDescription>{state.error}</AlertDescription>
                </Alert>
              )}

              <div className="space-y-2">
                <Label htmlFor="email">Email address</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="you@example.com"
                  required
                  autoComplete="email"
                  className="h-11"
                />
              </div>

              <Button type="submit" className="h-11 w-full" disabled={isPending}>
                {isPending ? 'Creating account...' : 'Create account'}
                {!isPending && <ArrowRight className="h-4 w-4" />}
              </Button>
            </form>

            <p className="mt-5 text-center text-sm text-muted-foreground">
              Already have an account?{' '}
              <Link href="/login" className="font-medium text-primary underline-offset-4 hover:underline">
                Sign in
              </Link>
            </p>
          </CardContent>
        </Card>
      )}
    </main>
  )
}
