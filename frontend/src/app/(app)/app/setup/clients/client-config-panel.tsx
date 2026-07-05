'use client'

import { useState } from 'react'
import { Bot, Code2, Laptop, MessageSquareText, Terminal } from 'lucide-react'
import { CodeBlockWithCopy } from '@/components/code-block-with-copy'
import { StatusBadge } from '@/components/status-badge'
import { cn } from '@/lib/utils'
import type { ClientSetupPayloadResponse } from '@/types/api'

const TABS = [
  { key: 'chatgpt_developer_mode' as const, label: 'ChatGPT', icon: MessageSquareText },
  { key: 'cursor' as const, label: 'Cursor', icon: Code2 },
  { key: 'vs_code' as const, label: 'VS Code', icon: Laptop },
  { key: 'claude_desktop' as const, label: 'Claude Desktop', icon: Bot },
  { key: 'generic_http' as const, label: 'HTTP MCP', icon: Terminal },
]

interface ClientConfigPanelProps {
  clients: {
    vs_code: ClientSetupPayloadResponse
    cursor: ClientSetupPayloadResponse
    chatgpt_developer_mode: ClientSetupPayloadResponse
    claude_desktop: ClientSetupPayloadResponse
    generic_http: ClientSetupPayloadResponse
  }
}

export function ClientConfigPanel({ clients }: ClientConfigPanelProps) {
  const [active, setActive] = useState<keyof typeof clients>('claude_desktop')
  const payload = clients[active]
  const isReady = payload.status === 'ready'

  return (
    <div className="grid gap-5 lg:grid-cols-[0.38fr_0.62fr]">
      <div className="space-y-1">
        {TABS.map((tab, i) => {
          const Icon = tab.icon
          const clientPayload = clients[tab.key]
          const tabReady = clientPayload.status === 'ready'
          const isActive = active === tab.key
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActive(tab.key)}
              className={cn(
                'group relative flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left transition-colors',
                isActive
                  ? 'border-border bg-card shadow-sm'
                  : 'border-transparent hover:bg-muted/40',
              )}
            >
              <span
                aria-hidden
                className={cn(
                  'absolute inset-y-1.5 left-0 w-[2px] rounded-r-full transition-colors',
                  isActive ? 'bg-primary' : 'bg-transparent',
                )}
              />
              <Icon
                className={cn(
                  'h-4 w-4 shrink-0 transition-colors',
                  isActive ? 'text-primary' : 'text-muted-foreground',
                )}
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-medium">
                  {tab.label}
                </span>
                <span className="mt-0.5 block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  {String(i + 1).padStart(2, '0')} ·{' '}
                  {tabReady ? 'ready' : clientPayload.status.replace(/_/g, ' ')}
                </span>
              </span>
              <span
                className={cn(
                  'h-1.5 w-1.5 shrink-0 rounded-full',
                  tabReady ? 'bg-emerald-500' : 'bg-muted-foreground/40',
                )}
              />
            </button>
          )
        })}
      </div>

      <div className="rounded-xl border border-border bg-card">
        <div className="flex flex-col gap-3 border-b border-border px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="eyebrow text-primary">target client</p>
            <h3 className="mt-1 font-display text-base font-semibold -tracking-[0.02em]">
              {payload.display_name}
            </h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              {isReady
                ? 'Copy the generated setup and follow the steps below.'
                : payload.availability_reason}
            </p>
          </div>
          <StatusBadge
            variant={isReady ? 'connected' : 'inactive'}
            label={isReady ? 'Ready' : payload.status.replace(/_/g, ' ')}
          />
        </div>

        {!isReady ? (
          <div className="m-5 rounded-lg border border-amber-200/80 bg-amber-50/70 p-4 text-sm leading-6 text-amber-900">
            {payload.availability_reason}
          </div>
        ) : (
          <div className="space-y-5 px-5 py-5">
            {payload.config_path_hint && (
              <div>
                <p className="eyebrow text-muted-foreground">Config location</p>
                <code className="mt-2 block rounded-md border border-border bg-muted/40 px-3 py-2 font-mono text-[12px] text-foreground">
                  {payload.config_path_hint}
                </code>
              </div>
            )}

            <div>
              <p className="eyebrow mb-2 text-muted-foreground">Configuration</p>
              <CodeBlockWithCopy code={payload.snippet} label="config" />
            </div>

            {payload.instructions.length > 0 && (
              <div>
                <p className="eyebrow mb-3 text-muted-foreground">Steps</p>
                <ol className="space-y-2.5">
                  {payload.instructions.map((step, index) => (
                    <li key={step} className="flex gap-3 text-sm leading-6">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-[10px] font-semibold text-primary">
                        {index + 1}
                      </span>
                      <span className="text-muted-foreground">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm leading-6 text-muted-foreground">
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-foreground">
                Auth ·{' '}
              </span>
              {payload.api_key_handling}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
