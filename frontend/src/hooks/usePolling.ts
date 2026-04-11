import { useEffect, useRef, useState, useCallback } from 'react'

interface UsePollingOptions {
  /** Interval in milliseconds (default: 5000) */
  interval?: number
  /** Start polling immediately (default: true) */
  immediate?: boolean
}

interface UsePollingResult<T> {
  data: T | null
  error: string | null
  loading: boolean
  refresh: () => void
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  options: UsePollingOptions = {},
): UsePollingResult<T> {
  const { interval = 5000, immediate = true } = options

  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const isMounted = useRef(true)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const run = useCallback(async () => {
    try {
      const result = await fetcherRef.current()
      if (isMounted.current) {
        setData(result)
        setError(null)
      }
    } catch (err) {
      if (isMounted.current) {
        setError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      if (isMounted.current) {
        setLoading(false)
      }
    }
  }, [])

  const refresh = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    void run().then(() => {
      if (isMounted.current) {
        timerRef.current = setInterval(() => void run(), interval)
      }
    })
  }, [run, interval])

  useEffect(() => {
    isMounted.current = true

    if (immediate) {
      void run()
    }

    timerRef.current = setInterval(() => void run(), interval)

    return () => {
      isMounted.current = false
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [run, interval, immediate])

  return { data, error, loading, refresh }
}
