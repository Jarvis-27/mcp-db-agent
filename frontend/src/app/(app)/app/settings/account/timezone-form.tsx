'use client'

import { useActionState, useState } from 'react'
import { Check, Globe2 } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDetectedTimezone } from '@/lib/use-detected-timezone'
import { updateTimezoneAction } from './actions'

interface TimezoneFormProps {
  currentTimezone: string
}

export function TimezoneForm({ currentTimezone }: TimezoneFormProps) {
  const [state, formAction, isPending] = useActionState(updateTimezoneAction, null)
  const detected = useDetectedTimezone()
  const [value, setValue] = useState(currentTimezone)

  const effectiveTimezone = state?.timezone ?? currentTimezone
  const detectionDiffers =
    detected && detected !== effectiveTimezone && detected !== value

  return (
    <form action={formAction} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="timezone">IANA time zone</Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id="timezone"
            name="timezone"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Asia/Kolkata"
            required
            className="h-10 font-mono text-sm"
          />
          <Button type="submit" disabled={isPending || value.trim() === ''}>
            {isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Use a standard IANA name such as <code>Asia/Kolkata</code>,{' '}
          <code>America/New_York</code>, or <code>Europe/Berlin</code>.
        </p>
      </div>

      {detectionDiffers && (
        <button
          type="button"
          onClick={() => setValue(detected)}
          className="inline-flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground hover:bg-muted"
        >
          <Globe2 className="h-3.5 w-3.5" />
          Use detected ({detected})
        </button>
      )}

      {state?.error && (
        <Alert variant="destructive">
          <AlertDescription>{state.error}</AlertDescription>
        </Alert>
      )}

      {state?.success && (
        <Alert>
          <Check className="h-4 w-4" />
          <AlertDescription>
            Time zone saved. Your daily quota window now resets at midnight in{' '}
            <span className="font-mono">{state.timezone ?? value}</span>.
          </AlertDescription>
        </Alert>
      )}
    </form>
  )
}
