import type { QueryResult } from '@/types/api'

export type PersistedChatMessage =
  | { id: string; role: 'user'; content: string }
  | { id: string; role: 'assistant'; result: QueryResult }
  | { id: string; role: 'error'; message: string }

const CACHE_PREFIX = 'querywise_chat_session'

function cacheKey(sessionId: string): string {
  return `${CACHE_PREFIX}:${sessionId}`
}

export function loadPersistedChatMessages(sessionId: string): PersistedChatMessage[] | null {
  try {
    const raw = localStorage.getItem(cacheKey(sessionId))
    if (!raw) {
      return null
    }

    const parsed = JSON.parse(raw) as PersistedChatMessage[]
    return Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function persistChatMessages(sessionId: string, messages: PersistedChatMessage[]): void {
  try {
    localStorage.setItem(cacheKey(sessionId), JSON.stringify(messages))
  } catch {
    // Ignore storage failures so chat remains functional.
  }
}

export function clearPersistedChatMessages(sessionId: string): void {
  try {
    localStorage.removeItem(cacheKey(sessionId))
  } catch {
    // Ignore storage failures.
  }
}