'use client'

import { useState } from 'react'
import { ChevronDown, ShieldAlert } from 'lucide-react'
import { CopyButton } from '@/components/copy-button'
import { cn } from '@/lib/utils'

interface FirewallHintProps {
  staticOutboundIp: string | null
  variant: 'form' | 'error'
}

export function FirewallHint({ staticOutboundIp, variant }: FirewallHintProps) {
  const [open, setOpen] = useState(false)

  if (!staticOutboundIp) return null

  const ipBlock = (
    <div className="mt-3 flex items-center gap-2">
      <span className="rounded-md border border-border bg-background px-2 py-1 font-mono text-xs">
        {staticOutboundIp}
      </span>
      <CopyButton text={staticOutboundIp} />
    </div>
  )

  if (variant === 'error') {
    return (
      <div className="mt-3 rounded-md border border-border bg-muted/40 p-3 text-sm">
        <div className="flex items-center gap-2 font-medium text-foreground">
          <ShieldAlert className="h-4 w-4 text-amber-600" />
          If your database has an IP allowlist or firewall
        </div>
        <p className="mt-1 text-muted-foreground">
          Add our outbound IP to the allowed sources and try again.
        </p>
        {ipBlock}
      </div>
    )
  }

  return (
    <div className="rounded-md border border-border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium text-foreground hover:bg-muted/60"
      >
        <span className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-amber-600" />
          Behind a firewall?
        </span>
        <ChevronDown
          className={cn(
            'h-4 w-4 text-muted-foreground transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>
      {open && (
        <div className="border-t border-border px-3 py-3 text-sm text-muted-foreground">
          If your database only accepts connections from certain IPs, allowlist
          our outbound address before connecting.
          {ipBlock}
        </div>
      )}
    </div>
  )
}
