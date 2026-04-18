import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api/client'

export type StreamEventType = 'start' | 'step' | 'tool_result' | 'text_delta' | 'done' | 'error' | 'eof'

export interface StreamEvent {
  type: StreamEventType
  [key: string]: unknown
}

export interface TaskStreamState {
  events: StreamEvent[]
  status: 'idle' | 'connecting' | 'streaming' | 'done' | 'error'
  finalResponse: string | null
  error: string | null
  usedTools: string[]
  createdPaths: string[]
  updatedPaths: string[]
  patchSummaries: string[]
}

function getApiKey(): string {
  if (typeof window === 'undefined') return ''
  return (
    window.localStorage.getItem('titanshift-api-key')?.trim() ||
    window.localStorage.getItem('titanshift-admin-api-key')?.trim() ||
    ''
  )
}

export function useTaskStream() {
  const [state, setState] = useState<TaskStreamState>({
    events: [],
    status: 'idle',
    finalResponse: null,
    error: null,
    usedTools: [],
    createdPaths: [],
    updatedPaths: [],
    patchSummaries: [],
  })

  const abortRef = useRef<AbortController | null>(null)

  const startStream = useCallback(
    async (requestBody: Record<string, unknown>) => {
      // Cancel any in-flight stream
      if (abortRef.current) {
        abortRef.current.abort()
      }
      const controller = new AbortController()
      abortRef.current = controller

      setState({
        events: [],
        status: 'connecting',
        finalResponse: null,
        error: null,
        usedTools: [],
        createdPaths: [],
        updatedPaths: [],
        patchSummaries: [],
      })

      try {
        const apiKey = getApiKey()
        const res = await fetch(`${API_BASE}/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(apiKey ? { 'X-Api-Key': apiKey } : {}),
          },
          body: JSON.stringify(requestBody),
          signal: controller.signal,
        })

        if (!res.ok) {
          const msg = `Stream request failed: ${res.status} ${res.statusText}`
          setState((prev) => ({ ...prev, status: 'error', error: msg }))
          return
        }

        setState((prev) => ({ ...prev, status: 'streaming' }))

        const reader = res.body?.getReader()
        if (!reader) {
          setState((prev) => ({ ...prev, status: 'error', error: 'Response body unavailable' }))
          return
        }

        const decoder = new TextDecoder()
        let buffer = ''

        const processLine = (line: string) => {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) return
          const payload = trimmed.slice(5).trim()
          if (!payload) return
          let event: StreamEvent
          try {
            event = JSON.parse(payload) as StreamEvent
          } catch {
            return
          }

          setState((prev) => {
            const newEvents = [...prev.events, event]
            const updates: Partial<TaskStreamState> = { events: newEvents }
            if (event.type === 'done') {
              updates.status = 'done'
              updates.finalResponse = typeof event.response === 'string' ? event.response : prev.finalResponse
              updates.usedTools = Array.isArray(event.used_tools) ? (event.used_tools as string[]) : prev.usedTools
              updates.createdPaths = Array.isArray(event.created_paths) ? (event.created_paths as string[]) : prev.createdPaths
              updates.updatedPaths = Array.isArray(event.updated_paths) ? (event.updated_paths as string[]) : prev.updatedPaths
              updates.patchSummaries = Array.isArray(event.patch_summaries) ? (event.patch_summaries as string[]) : prev.patchSummaries
            } else if (event.type === 'error') {
              updates.status = 'error'
              updates.error = typeof event.message === 'string' ? event.message : 'Unknown stream error'
            } else if (event.type === 'eof') {
              if (prev.status === 'streaming') updates.status = 'done'
            }
            return { ...prev, ...updates }
          })
        }

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            processLine(line)
          }
        }
        // Process remaining buffer
        if (buffer.trim()) processLine(buffer)

        setState((prev) => {
          if (prev.status === 'streaming') return { ...prev, status: 'done' }
          return prev
        })
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        const msg = err instanceof Error ? err.message : String(err)
        setState((prev) => ({ ...prev, status: 'error', error: msg }))
      }
    },
    [],
  )

  const cancelStream = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setState((prev) => (prev.status === 'streaming' ? { ...prev, status: 'idle' } : prev))
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  return { state, startStream, cancelStream }
}
