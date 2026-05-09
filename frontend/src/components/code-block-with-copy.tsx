'use client'

import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { cn } from '@/lib/utils'

interface CodeBlockWithCopyProps {
  code: string
  inline?: boolean
  label?: string
  className?: string
}

export function CodeBlockWithCopy({
  code,
  inline = false,
  label,
  className,
}: CodeBlockWithCopyProps) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code)
    } catch {
      const el = document.createElement('textarea')
      el.value = code
      el.style.position = 'fixed'
      el.style.opacity = '0'
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (inline) {
    return (
      <div
        className={cn(
          'group flex items-stretch overflow-hidden rounded-lg border border-border bg-muted/40',
          className,
        )}
      >
        <code className="min-w-0 flex-1 truncate px-3 py-2.5 font-mono text-[12.5px] text-foreground">
          {code}
        </code>
        <button
          onClick={handleCopy}
          className="flex shrink-0 items-center gap-1.5 border-l border-border bg-card px-3 py-2.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          title="Copy to clipboard"
          type="button"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-emerald-600" />
              <span className="text-emerald-700">copied</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span>copy</span>
            </>
          )}
        </button>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-foreground/10 bg-foreground/[0.97] text-background shadow-sm',
        className,
      )}
    >
      {(label || true) && (
        <div className="flex items-center justify-between border-b border-white/10 px-3.5 py-2">
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-background/55">
            {label ?? 'snippet'}
          </span>
          <button
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-background/75 transition-colors hover:bg-white/10 hover:text-background"
            title="Copy to clipboard"
            type="button"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-emerald-400" />
                copied
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                copy
              </>
            )}
          </button>
        </div>
      )}
      <pre className="overflow-x-auto px-3.5 py-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap break-all text-background/90">
        {code}
      </pre>
    </div>
  )
}
