import { useState, useRef, useEffect, useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useOutletContext } from 'react-router-dom'
import { queryApi, type QueryStageEvent } from '@/api/queryApi'
import { useSessionMessages } from '@/hooks/useThreads'
import { PureMultimodalInput } from '@/components/ui/multimodal-ai-chat-input'
import { SpotlightTable } from '@/components/ui/spotlight-table'
import { RecentQuestions, saveRecentQuestion } from '@/components/RecentQuestions'
import { loadPersistedChatMessages, persistChatMessages } from '@/lib/chat-session-cache'
import type { QueryResult } from '@/types/api'
import type { ChatLayoutContext } from '@/components/layout/ChatLayout'
import { Bot, User, AlertCircle, ChevronDown, ChevronUp, Copy, Check, Zap, MessageSquareOff, Loader2 } from 'lucide-react'

// ── Message types ──────────────────────────────────────────────────────────────
type ChatMessage =
  | { id: string; role: 'user'; content: string }
  | { id: string; role: 'assistant'; result: QueryResult }
  | { id: string; role: 'error'; message: string }

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
            {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3 text-muted-foreground" />}
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
    <div className="flex gap-3 group">
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
                className="px-2 py-0.5 text-xs rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-medium"
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
    <div className="flex gap-3 justify-end group">
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
          Ask questions about your data in plain English. I'll generate SQL, execute it, and explain the results.
        </p>
      </div>
      <div className="w-full max-w-lg">
        <RecentQuestions onSelect={onExample} />
      </div>
    </div>
  )
}

// ── No thread selected state ───────────────────────────────────────────────────
function NoThreadSelected() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex items-center justify-center w-14 h-14 mx-auto bg-muted rounded-2xl">
        <MessageSquareOff className="h-7 w-7 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <h2 className="text-base font-medium text-foreground">No chat selected</h2>
        <p className="text-sm text-muted-foreground max-w-xs">
          Click "New Chat" in the sidebar to start a conversation, or select an existing thread.
        </p>
      </div>
    </div>
  )
}

// ── Reconstruct messages from session history ─────────────────────────────────
function buildMessagesFromHistory(
  historyItems: Array<{
    id: string
    natural_language: string
    result_summary: string | null
    execution_status: string
    error_message: string | null
    final_sql: string | null
    generated_sql: string | null
    row_count: number | null
    execution_time_ms: number | null
    retry_count: number
    turn_type: string
  }>
): ChatMessage[] {
  const messages: ChatMessage[] = []
  for (const item of historyItems) {
    messages.push({
      id: `${item.id}-user`,
      role: 'user',
      content: item.natural_language,
    })
    if (item.execution_status === 'error' && item.error_message) {
      messages.push({
        id: `${item.id}-error`,
        role: 'error',
        message: item.error_message,
      })
    } else {
      // Reconstruct a QueryResult shape for display
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
      messages.push({
        id: `${item.id}-assistant`,
        role: 'assistant',
        result,
      })
    }
  }
  return messages
}

// ── Main ChatQueryPage ─────────────────────────────────────────────────────────
export function ChatQueryPage() {
  const { threadId } = useParams<{ threadId?: string }>()
  const { connectionId } = useOutletContext<ChatLayoutContext>()
  const queryClient = useQueryClient()

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [pipelineStage, setPipelineStage] = useState<QueryStageEvent | null>(null)
  const [attachments, setAttachments] = useState<{ url: string; name: string; contentType: string; size: number }[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Load session history on mount / thread change
  const { data: sessionMessages, isLoading: loadingHistory } = useSessionMessages(threadId)

  useEffect(() => {
    // Reset when thread changes
    setMessages([])
    setHistoryLoaded(false)
  }, [threadId])

  useEffect(() => {
    if (!threadId || historyLoaded) {
      return
    }

    const cachedMessages = loadPersistedChatMessages(threadId)
    if (cachedMessages) {
      setMessages(cachedMessages)
      setHistoryLoaded(true)
      return
    }

    if (sessionMessages && !historyLoaded) {
      const restored = buildMessagesFromHistory(sessionMessages)
      setMessages(restored)
      setHistoryLoaded(true)
    }
  }, [historyLoaded, sessionMessages, threadId])

  useEffect(() => {
    if (!threadId || !historyLoaded) {
      return
    }

    persistChatMessages(threadId, messages)
  }, [historyLoaded, messages, threadId])

  // Scroll to bottom on new messages
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  const mutation = useMutation<QueryResult, Error, { question: string; connId: string }>({
    mutationFn: async ({ question, connId }: { question: string; connId: string }) => {
      return await queryApi.executeStream(
        {
          connection_id: connId,
          question,
          session_id: threadId,
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
      // Invalidate thread list so title + message count update in sidebar
      if (threadId && connectionId) {
        queryClient.invalidateQueries({ queryKey: ['threads', connectionId] })
        queryClient.invalidateQueries({ queryKey: ['session-messages', threadId] })
      }
    },
    onError: (error: unknown) => {
      setPipelineStage(null)
      const message = error instanceof Error ? error.message : 'An unexpected error occurred'
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

      setMessages((prev) => {
        const next = [...prev, userMsg]
        mutation.mutate({ question: content.trim(), connId: connectionId })
        return next
      })
    },
    [connectionId, mutation, queryClient, threadId],
  )

  const hasMessages = messages.length > 0

  // No thread selected — show prompt to create one
  if (!threadId) {
    return (
      <div className="flex flex-col h-full min-h-0">
        <div className="shrink-0 flex items-center px-4 py-2 border-b border-gray-200 bg-white">
          <h1 className="text-sm font-semibold text-gray-900">Chat</h1>
        </div>
        <NoThreadSelected />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Top bar */}
      <div className="shrink-0 flex items-center justify-between gap-3 px-4 py-2 border-b border-gray-200 bg-white">
        <h1 className="text-sm font-semibold text-gray-900 truncate">Chat</h1>
        {connectionId && (
          <span className="text-xs text-gray-400 shrink-0">
            Thread active
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto custom-scrollbar bg-white">
        {loadingHistory ? (
          <div className="flex-1 flex items-center justify-center p-8">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Loading conversation...</span>
            </div>
          </div>
        ) : !hasMessages ? (
          <WelcomeScreen onExample={sendMessage} />
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            {messages.map((msg) => {
              if (msg.role === 'user') {
                return <UserMessage key={msg.id} content={msg.content} />
              }
              if (msg.role === 'assistant') {
                return (
                  <AssistantMessage
                    key={msg.id}
                    result={msg.result}
                    onFollowup={sendMessage}
                  />
                )
              }
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
          {!connectionId && (
            <p className="text-xs text-amber-600 mb-2 text-center">
              Select a database connection in the sidebar to start querying.
            </p>
          )}
          <PureMultimodalInput
            chatId={threadId ?? 'new'}
            messages={[]}
            attachments={attachments}
            setAttachments={setAttachments}
            onSendMessage={({ input }) => sendMessage(input)}
            onStopGenerating={() => mutation.reset()}
            isGenerating={mutation.isPending}
            canSend={!!connectionId && !mutation.isPending}
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
