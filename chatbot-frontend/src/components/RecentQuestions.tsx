const BASE_STORAGE_KEY = 'qw_recent_questions'
const MAX_RECENT = 3

/**
 * Decode the `sub` claim from a JWT without verifying the signature.
 * We only need the user ID to namespace localStorage — no security concern here.
 */
function getUserIdFromToken(): string | null {
  try {
    const token = sessionStorage.getItem('qw_auth_token')
    if (!token) return null
    const payload = token.split('.')[1]
    if (!payload) return null
    // atob needs standard base64 — JWT uses base64url, so patch the padding
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    const claims = JSON.parse(json) as Record<string, unknown>
    return typeof claims.sub === 'string' ? claims.sub : null
  } catch {
    return null
  }
}

/** Returns a per-user localStorage key, falling back to the shared key if unauthenticated. */
function storageKey(): string {
  const uid = getUserIdFromToken()
  return uid ? `${BASE_STORAGE_KEY}_${uid}` : BASE_STORAGE_KEY
}

export function saveRecentQuestion(question: string): void {
  try {
    const key = storageKey()
    const raw = localStorage.getItem(key)
    const existing: string[] = raw ? (JSON.parse(raw) as string[]) : []
    // Dedup: remove if already present, then prepend
    const deduped = existing.filter((q) => q !== question)
    const next = [question, ...deduped].slice(0, MAX_RECENT)
    localStorage.setItem(key, JSON.stringify(next))
  } catch {
    // localStorage unavailable — silently ignore
  }
}

function loadRecentQuestions(): string[] {
  try {
    const raw = localStorage.getItem(storageKey())
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

interface RecentQuestionsProps {
  onSelect: (question: string) => void
}

export function RecentQuestions({ onSelect }: RecentQuestionsProps) {
  const questions = loadRecentQuestions()

  if (questions.length === 0) return null

  return (
    <div className="w-full">
      <p className="text-xs text-muted-foreground mb-2 font-medium">Recent questions</p>
      <div className="flex flex-col gap-2">
        {questions.map((q, i) => (
          <button
            key={i}
            onClick={() => onSelect(q)}
            className="px-3 py-2 text-xs text-left rounded-lg border border-border bg-card hover:bg-accent hover:text-accent-foreground transition-colors leading-snug truncate"
            title={q}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
