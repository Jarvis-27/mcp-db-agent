'use client'

import { useState } from 'react'
import { Code2, Laptop, MessageSquareText, Terminal } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { CodeBlockWithCopy } from '@/components/code-block-with-copy'
import { cn } from '@/lib/utils'
import type { ClientSetupPayloadResponse } from '@/types/api'

const TABS = [
  { key: 'chatgpt_developer_mode' as const, label: 'ChatGPT', icon: MessageSquareText },
  { key: 'cursor' as const, label: 'Cursor', icon: Code2 },
  { key: 'vs_code' as const, label: 'VS Code', icon: Laptop },
  { key: 'generic_http' as const, label: 'HTTP MCP', icon: Terminal },
]

interface ClientConfigPanelProps {
  clients: {
    vs_code: ClientSetupPayloadResponse
    cursor: ClientSetupPayloadResponse
    chatgpt_developer_mode: ClientSetupPayloadResponse
    generic_http: ClientSetupPayloadResponse
  }
}

export function ClientConfigPanel({ clients }: ClientConfigPanelProps) {
  const [active, setActive] = useState<keyof typeof clients>('chatgpt_developer_mode')
  const payload = clients[active]
  const isReady = payload.status === 'ready'

  return (
    <div className="grid gap-5 lg:grid-cols-[0.42fr_0.58fr]">
      <div className="space-y-2">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const clientPayload = clients[tab.key]
          const tabReady = clientPayload.status === 'ready'
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActive(tab.key)}
              className={cn(
                'flex w-full items-center gap-3 rounded-2xl border p-3 text-left transition-all',
                active === tab.key
                  ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                  : 'bg-background hover:bg-muted/50',
              )}
            >
              <span
                className={cn(
                  'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl',
                  active === tab.key ? 'bg-white/15' : 'bg-primary/10 text-primary',
                )}
              >
                <Icon className="h-5 w-5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{tab.label}</span>
                <span
                  className={cn(
                    'mt-0.5 block text-xs',
                    active === tab.key ? 'text-primary-foreground/70' : 'text-muted-foreground',
                  )}
                >
                  {tabReady ? 'Ready to configure' : clientPayload.status.replace(/_/g, ' ')}
                </span>
              </span>
            </button>
          )
        })}
      </div>

      <div className="rounded-3xl border bg-background p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="text-xl font-semibold">{payload.display_name}</h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              {isReady
                ? 'Copy the generated setup and follow the steps below.'
                : payload.availability_reason}
            </p>
          </div>
          <Badge variant={isReady ? 'default' : 'secondary'}>
            {isReady ? 'Ready' : payload.status.replace(/_/g, ' ')}
          </Badge>
        </div>

        {!isReady ? (
          <div className="mt-5 rounded-2xl bg-amber-50 p-4 text-sm leading-6 text-amber-900 ring-1 ring-amber-200">
            {payload.availability_reason}
          </div>
        ) : (
          <div className="mt-6 space-y-5">
            {payload.config_path_hint && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  Config location
                </p>
                <code className="mt-2 block rounded-2xl bg-muted/70 px-3 py-2 text-xs font-mono text-muted-foreground">
                  {payload.config_path_hint}
                </code>
              </div>
            )}

            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Configuration
              </p>
              <CodeBlockWithCopy code={payload.snippet} />
            </div>

            {payload.instructions.length > 0 && (
              <div>
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  Steps
                </p>
                <ol className="space-y-2">
                  {payload.instructions.map((step, index) => (
                    <li key={step} className="flex gap-3 text-sm leading-6">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                        {index + 1}
                      </span>
                      <span className="text-muted-foreground">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            <div className="rounded-2xl bg-muted/70 px-4 py-3 text-sm leading-6 text-muted-foreground">
              <span className="font-semibold text-foreground">Auth:</span>{' '}
              {payload.api_key_handling}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
