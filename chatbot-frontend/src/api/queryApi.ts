import { api, getApiBaseUrl } from './client'
import type { QueryResult, QueryHistory } from '../types/api'

export interface QueryStageEvent {
  type: 'stage'
  stage: 'understanding' | 'generating_sql' | 'running_query' | 'interpreting'
  label: string
  progress: number
}

export interface QueryResultEvent {
  type: 'result'
  data: QueryResult
}

export interface QueryErrorEvent {
  type: 'error'
  message: string
  status_code?: number
}
export interface QueryTokenEvent {
  type: 'token'
  content: string
}

export type QueryStreamEvent = QueryStageEvent | QueryResultEvent | QueryErrorEvent | QueryTokenEvent
async function buildStreamRequestError(response: Response): Promise<Error> {
  let message = `Request failed with status ${response.status}`

  try {
    const contentType = response.headers.get('content-type') ?? ''
    if (contentType.includes('application/json')) {
      const body = (await response.json()) as { error?: string }
      if (body.error) {
        message = body.error
      }
    } else {
      const text = (await response.text()).trim()
      if (text) {
        message = text
      }
    }
  } catch {
    // Fall back to the HTTP status message computed above.
  }

  return new Error(message)
}

export const queryApi = {
  execute: (data: {
    connection_id: string
    question: string
    session_id?: string
    clear_context?: boolean
  }) => api.post<QueryResult>('/query', data).then((r) => r.data),

  executeStream: async (
    data: {
      connection_id: string
      question: string
      session_id?: string
      clear_context?: boolean
    },
    onEvent: (event: QueryStreamEvent) => void,
  ) => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }

    // Read CSRF token from the non-HttpOnly cookie and attach as header
    const csrfMatch = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/)
    const csrfToken = csrfMatch ? decodeURIComponent(csrfMatch[1]) : null
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken
    }

    const response = await fetch(`${getApiBaseUrl()}/api/v1/query/stream`, {
      method: 'POST',
      headers,
      credentials: 'include',
      body: JSON.stringify(data),
    })

    if (!response.ok) {
      throw await buildStreamRequestError(response)
    }
    if (!response.body) {
      throw new Error('Streaming response body was empty')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: QueryResult | null = null

    const handleSseChunk = (chunk: string) => {
      const event = chunk
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('')

      if (!event) return

      const parsed = JSON.parse(event) as QueryStreamEvent
      onEvent(parsed)
      if (parsed.type === 'result') {
        finalResult = parsed.data
      }
      if (parsed.type === 'error') {
        throw new Error(parsed.message)
      }
    }

    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? ''

      for (const chunk of chunks) {
        if (!chunk.trim()) continue
        handleSseChunk(chunk)
      }
    }

    if (buffer.trim()) {
      handleSseChunk(buffer)
    }

    if (!finalResult) {
      throw new Error('Stream completed without a final result')
    }

    return finalResult
  },

  history: (params?: { connection_id?: string; limit?: number; offset?: number }) =>
    api.get<QueryHistory[]>('/query-history', { params }).then((r) => r.data),

  toggleFavorite: (id: string) =>
    api.patch<{ is_favorite: boolean }>(`/query-history/${id}/favorite`).then((r) => r.data),
}
