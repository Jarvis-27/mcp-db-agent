'use client'

import { useActionState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { updateDatabaseAction } from './actions'

type State = { error?: string; success?: boolean } | null

export function DatabaseSettingsForm() {
  const [state, formAction, isPending] = useActionState<State, FormData>(
    updateDatabaseAction,
    null,
  )

  return (
    <form action={formAction} className="space-y-5">
      {state?.error && (
        <Alert variant="destructive">
          <AlertDescription>{state.error}</AlertDescription>
        </Alert>
      )}
      {state?.success && (
        <Alert className="border-emerald-200/80 bg-emerald-50/70 text-emerald-900">
          <AlertDescription>Database connection updated successfully.</AlertDescription>
        </Alert>
      )}

      <div className="space-y-2">
        <Label
          htmlFor="database_url"
          className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground"
        >
          New connection string
        </Label>
        <Input
          id="database_url"
          name="database_url"
          type="text"
          placeholder="postgresql://user:password@host:5432/dbname"
          required
          className="h-11 font-mono text-[13px]"
        />
        <p className="text-xs leading-5 text-muted-foreground">
          Supports{' '}
          <code className="font-mono text-[11px] text-foreground">postgresql://</code>{' '}
          and{' '}
          <code className="font-mono text-[11px] text-foreground">mysql+pymysql://</code>.
          The backend validates and tests the connection before replacing the stored
          credential.
        </p>
      </div>

      <Button type="submit" className="h-11" disabled={isPending}>
        {isPending ? 'Testing connection…' : 'Update database'}
      </Button>
    </form>
  )
}
