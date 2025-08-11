'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

function safeParse<T>(raw: string | null, fallback: T): T {
  try { return raw ? JSON.parse(raw) as T : fallback } catch { return fallback }
}

export function useLocalStorage<T>(key: string, initialValue: T) {
  const isClient = typeof window !== 'undefined';

  const [value, setValue] = useState<T>(() => {
    if (!isClient) return initialValue
    return safeParse<T>(window.localStorage.getItem(key), initialValue)
  })

  const mounted = useRef(false)

  useEffect(() => {
    if (!isClient) return
    if (!mounted.current) {
      mounted.current = true
      const stored = window.localStorage.getItem(key)
      if (stored !== null) setValue(safeParse<T>(stored, initialValue))
      return
    }
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {}
  }, [isClient, key, value, initialValue])

  useEffect(() => {
    if (!isClient) return
    const onStorage = (e: StorageEvent) => {
      if (e.key !== key) return
      setValue(prev => safeParse<T>(e.newValue, prev))
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [isClient, key])

  const setLSValue = useCallback((next: T | ((prev: T) => T)) => {
    setValue(prev => {
      const v = typeof next === 'function' ? (next as (p: T) => T)(prev) : next
      try { if (isClient) window.localStorage.setItem(key, JSON.stringify(v)) } catch {}
      return v
    })
  }, [isClient, key])

  return [value, setLSValue] as const
}
