import { useState, useRef, useEffect, useCallback } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { queryApi, type QueryStageEvent } from '@/api/queryApi'
import { sessionApi } from '@/api/sessionApi'
import { PureMultimodalInput } from '@/components/ui/multimodal-ai-chat-input'
import { SpotlightTable } from '@/components/ui/spotlight-table'
import { RecentQuestions, saveRecentQuestion } from '@/components/RecentQuestions'
import { loadPersistedChatMessages, persistChatMessages } from '@/lib/chat-session-cache'
import type { QueryResult, ChatSessionMessage } from '@/types/api'
import {
  Bot,
  User,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  Zap,
  Loader2,
} from 'lucide-react'

// ── Constants ──────────────────────────────────────────────────────────────────
const SESSION_STORAGE_KEY = 'qw_session_id'

// ── Message types ──────────────────────────────────────────────────────────────
type ChatMessage =
  | { id: string; role: 'user'; content: string }
  | { id: string; role: 'assistant'; result: QueryResult }
  | { id: string; role: 'error'; message: string }

// ── Reconstruct messages from session history ─────────────────────────────────
function buildMessagesFromHistory(historyItems: ChatSessionMessage[]): ChatMessage[] {
  const messages: ChatMessage[] = []
  for (const item of historyItems) {
    messages.push({ id: `${item.id}-user`, role: 'user', content: item.natural_language })
    if (item.execution_status === 'error' && item.error_message) {
      messages.push({ id: `${item.id}-error`, role: 'error', message: item.error_message })
    } else {
      const result: QueryResult = {
        id: item.id,
        question: item.natural_language,
        generated_sql: item.generated_sql ?? '',
        final_sql: item.final_sql ?? '',
        explanation: '',
        columns: [],
        column_types: [],
        rows: [],
        row_count: item.row_count ?? 0,
        execution_time_ms: item.execution_time_ms ?? 0,
        truncated: false,
        summary: item.turn_type === 'clarification' ? null : item.result_summary,
        highlights: [],
        suggested_followups: [],
        llm_provider: null,
        llm_model: null,
        retry_count: item.retry_count,
        turn_type: item.turn_type,
        clarification_message: item.turn_type === 'clarification' ? item.result_summary : null,
        clarification_options: [],
      }
      messages.push({ id: `${item.id}-assistant`, role: 'assistant', result })
    }
  }
  return messages
}

// ── SQL collapsible block ──────────────────────────────────────────────────────
function SqlBlock({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    void navigator.clipboard.writeText(sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="mt-3 rounded-lg border border-border overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 bg-muted/50 hover:bg-muted text-xs font-medium text-muted-foreground transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <Zap className="h-3 w-3" />
          View generated SQL
        </span>
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>
      {open && (
        <div className="relative">
          <pre className="p-3 text-xs font-mono bg-card text-foreground overflow-x-auto whitespace-pre-wrap leading-relaxed">
            {sql}
          </pre>
          <button
            onClick={handleCopy}
            className="absolute top-2 right-2 p-1 rounded bg-muted hover:bg-accent transition-colors"
            title="Copy SQL"
          >
            {copied ? (
              <Check className="h-3 w-3 text-green-500" />
            ) : (
              <Copy className="h-3 w-3 text-muted-foreground" />
            )}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Assistant message bubble ───────────────────────────────────────────────────
function AssistantMessage({
  result,
  onFollowup,
}: {
  result: QueryResult
  onFollowup: (q: string) => void
}) {
  const primaryText = result.clarification_message ?? result.summary
  const suggestionOptions = result.turn_type === 'clarification'
    ? result.clarification_options
    : result.suggested_followups

  return (
    <div className="flex gap-3">
      <div className="shrink-0 w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center">
        <Bot className="h-4 w-4 text-gray-700" />
      </div>
      <div className="flex-1 min-w-0 space-y-3">
        {primaryText && (
          <p className="text-sm text-gray-900 leading-relaxed">{primaryText}</p>
        )}
        {result.highlights.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {result.highlights.map((h, i) => (
              <span
                key={i}
                className="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700 font-medium"
              >
                {h}
              </span>
            ))}
          </div>
        )}
        {suggestionOptions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {suggestionOptions.map((option) => (
              <button
                key={option}
                onClick={() => onFollowup(option)}
                className="rounded-full border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 transition-colors hover:border-gray-900 hover:text-gray-900"
              >
                {option}
              </button>
            ))}
          </div>
        )}
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{result.row_count} rows</span>
          <span>·</span>
          <span>{result.execution_time_ms}ms</span>
          {result.retry_count > 0 && (
            <>
              <span>·</span>
              <span className="text-amber-500">{result.retry_count} retries</span>
            </>
          )}
        </div>
        {result.rows.length > 0 && (
          <SpotlightTable
            columns={result.columns}
            rows={result.rows}
            truncated={result.truncated}
            rowCount={result.row_count}
          />
        )}
        {result.final_sql && <SqlBlock sql={result.final_sql} />}
      </div>
    </div>
  )
}

// ── User message bubble ────────────────────────────────────────────────────────
function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex gap-3 justify-end">
      <div className="max-w-[75%]">
        <div className="px-4 py-2.5 rounded-2xl rounded-tr-sm bg-gray-900 text-white text-sm leading-relaxed">
          {content}
        </div>
      </div>
      <div className="shrink-0 w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center">
        <User className="h-4 w-4 text-gray-700" />
      </div>
    </div>
  )
}

// ── Error message ──────────────────────────────────────────────────────────────
function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="flex gap-3">
      <div className="shrink-0 w-8 h-8 rounded-full bg-destructive/10 flex items-center justify-center">
        <AlertCircle className="h-4 w-4 text-destructive" />
      </div>
      <div className="flex-1 px-4 py-2.5 rounded-2xl rounded-tl-sm bg-destructive/10 border border-destructive/20">
        <p className="text-sm text-destructive font-medium mb-0.5">Error</p>
        <p className="text-sm text-destructive/80">{message}</p>
      </div>
    </div>
  )
}

// ── Typing indicator ───────────────────────────────────────────────────────────
function TypingIndicator({ stage }: { stage: QueryStageEvent | null }) {
  const progress = stage?.progress ?? 15

  return (
    <div className="flex gap-3 items-start">
      <div className="shrink-0 w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center">
        <Bot className="h-4 w-4 text-gray-700" />
      </div>
      <div className="min-w-[260px] max-w-[340px] px-4 py-3 rounded-2xl rounded-tl-sm bg-muted">
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 shrink-0 animate-spin text-gray-700" />
          <div className="flex-1 min-w-0">
            <div className="h-1.5 rounded-full bg-gray-200 overflow-hidden">
              <div
                className="h-full rounded-full bg-gray-900 transition-all duration-500 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">{stage?.label ?? 'Extracting intent...'}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Welcome screen ─────────────────────────────────────────────────────────────
function WelcomeScreen({ onExample }: { onExample: (q: string) => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-8 p-8">
      <div className="text-center space-y-3">
        <div className="flex items-center justify-center w-16 h-16 mx-auto bg-gray-900 rounded-2xl shadow-lg">
          <Bot className="h-8 w-8 text-white" />
        </div>
        <h1 className="text-2xl font-semibold text-gray-900">How can I help you?</h1>
        <p className="text-sm text-gray-500 max-w-md">
          Ask questions about your data in plain English. I'll generate SQL, execute it, and explain
          the results.
        </p>
      </div>
      <div className="w-full max-w-lg">
        <RecentQuestions onSelect={onExample} />
      </div>
    </div>
  )
}

// ── No connection / auth error state ──────────────────────────────────────────
function SetupError({ message }: { message: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex items-center justify-center w-14 h-14 mx-auto bg-destructive/10 rounded-2xl">
        <AlertCircle className="h-7 w-7 text-destructive" />
      </div>
      <div className="space-y-1 max-w-sm">
        <h2 className="text-base font-medium text-foreground">Unable to start chat</h2>
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  )
}

// ── Main StandaloneChatPage ────────────────────────────────────────────────────
export function StandaloneChatPage() {
  // Read from sessionStorage (written by main.tsx from URL params)
  const connectionId = sessionStorage.getItem('qw_connection_id') ?? ''

  const [sessionId, setSessionId] = useState<string | null>(
    () => sessionStorage.getItem(SESSION_STORAGE_KEY),
  )
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [pipelineStage, setPipelineStage] = useState<QueryStageEvent | null>(null)
  const [attachments, setAttachments] = useState<
    { url: string; name: string; contentType: string; size: number }[]
  >([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const autoCreating = useRef(false)

  // ── Session history restore (on tab refresh) ──────────────────────────────
  const { data: sessionMessages, isLoading: loadingHistory } = useQuery({
    queryKey: ['session-messages', sessionId],
    queryFn: () => sessionApi.messages(sessionId!),
    enabled: !!sessionId,
    staleTime: 0,
  })

  useEffect(() => {
    if (!sessionId || historyLoaded) {
      return
    }

    const cachedMessages = loadPersistedChatMessages(sessionId)
    if (cachedMessages) {
      setMessages(cachedMessages)
      setHistoryLoaded(true)
      return
    }

    if (sessionMessages) {
      const restoredMessages = buildMessagesFromHistory(sessionMessages)
      setMessages(restoredMessages)
      setHistoryLoaded(true)
    }
  }, [historyLoaded, sessionId, sessionMessages])

  useEffect(() => {
    if (!sessionId || !historyLoaded) {
      return
    }

    persistChatMessages(sessionId, messages)
  }, [historyLoaded, messages, sessionId])

  // ── Auto-create session on first load (no stored session) ─────────────────
  useEffect(() => {
    if (sessionId || autoCreating.current) return
    if (!connectionId) {
      setSessionError(
        'No database connection was provided. Please open this page from the QueryWise dashboard.',
      )
      return
    }
    autoCreating.current = true
    sessionApi
      .create({ connection_id: connectionId })
      .then((session) => {
        sessionStorage.setItem(SESSION_STORAGE_KEY, session.id)
        setSessionId(session.id)
      })
      .catch(() => {
        setSessionError(
          'Failed to start a chat session. Your session may have expired — please sign in again.',
        )
      })
      .finally(() => {
        autoCreating.current = false
      })
  }, [connectionId, sessionId])

  // ── Scroll to bottom on new messages ─────────────────────────────────────
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  // ── Query mutation ────────────────────────────────────────────────────────
  const mutation = useMutation<QueryResult, Error, {
    question: string
  }>({
    mutationFn: async ({ question }: { question: string }) => {
      return await queryApi.executeStream(
        {
          connection_id: connectionId,
          question,
          session_id: sessionId ?? undefined,
        },
        (event) => {
          if (event.type === 'stage') setPipelineStage(event)
        },
      )
    },
    onMutate: () => {
      setPipelineStage(null)
    },
    onSuccess: (result) => {
      setPipelineStage(null)
      setMessages((prev) => [
        ...prev,
        { id: `${Date.now()}-assistant`, role: 'assistant', result },
      ])
    },
    onError: (error: unknown) => {
      setPipelineStage(null)
      const message =
        error instanceof Error ? error.message : 'An unexpected error occurred'
      setMessages((prev) => [
        ...prev,
        { id: `${Date.now()}-error`, role: 'error', message },
      ])
    },
  })

  const sendMessage = useCallback(
    (content: string) => {
      if (!content.trim() || !connectionId || mutation.isPending) return

      saveRecentQuestion(content.trim())

      const userMsg: ChatMessage = {
        id: `${Date.now()}-user`,
        role: 'user',
        content: content.trim(),
      }

      setMessages((prev) => [...prev, userMsg])
      mutation.mutate({ question: content.trim() })
    },
    [connectionId, mutation],
  )

  const hasMessages = messages.length > 0
  const isReady = !!sessionId && !sessionError

  return (
    <div className="flex flex-col h-screen bg-white overflow-hidden">
      {/* Minimal top bar */}
      <header className="shrink-0 flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-white">
        <div className="flex items-center justify-center w-7 h-7 bg-gray-900 rounded-lg">
          <Bot className="h-3.5 w-3.5 text-white" />
        </div>
        <span className="text-sm font-semibold text-gray-900">QueryWise</span>
      </header>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto bg-white">
        {sessionError ? (
          <SetupError message={sessionError} />
        ) : loadingHistory || (!sessionId && !sessionError) ? (
          <div className="flex-1 flex items-center justify-center p-8">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Starting chat...</span>
            </div>
          </div>
        ) : !hasMessages ? (
          <WelcomeScreen onExample={sendMessage} />
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            {messages.map((msg) => {
              if (msg.role === 'user') return <UserMessage key={msg.id} content={msg.content} />
              if (msg.role === 'assistant')
                return <AssistantMessage key={msg.id} result={msg.result} onFollowup={sendMessage} />
              return <ErrorMessage key={msg.id} message={msg.message} />
            })}
            {mutation.isPending && <TypingIndicator stage={pipelineStage} />}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="shrink-0 border-t border-gray-200 bg-white px-4 py-3">
        <div className="max-w-3xl mx-auto">
          {!isReady && !sessionError && (
            <p className="text-xs text-gray-400 text-center mb-2">Setting up your session...</p>
          )}
          <PureMultimodalInput
            chatId={sessionId ?? 'init'}
            messages={[]}
            attachments={attachments}
            setAttachments={setAttachments}
            onSendMessage={({ input }) => sendMessage(input)}
            onStopGenerating={() => mutation.reset()}
            isGenerating={mutation.isPending}
            canSend={isReady && !mutation.isPending}
            hideSuggestions
          />
          <p className="text-center text-[10px] text-gray-400 mt-2">
            Press Enter to send · Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  )
}
