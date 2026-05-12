'use client'

import { useSyncExternalStore } from 'react'

function subscribe() {
  return () => {}
}

function getClientSnapshot(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    return ''
  }
}

function getServerSnapshot(): string {
  return ''
}

export function useDetectedTimezone(): string {
  return useSyncExternalStore(subscribe, getClientSnapshot, getServerSnapshot)
}
