import { Injectable, signal, computed } from '@angular/core';
import { Router } from '@angular/router';

import { getRuntimeApiUrl } from '../utils/api';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content?: string;
  result?: QueryResult;
  errorMessage?: string;
}

export interface QueryResult {
  id: string;
  question: string;
  generated_sql: string | null;
  final_sql: string | null;
  explanation: string | null;
  columns: string[];
  column_types: string[];
  rows: unknown[][];
  row_count: number;
  execution_time_ms: number | null;
  truncated: boolean;
  summary: string | null;
  highlights: string[];
  suggested_followups: string[];
  clarification_message: string | null;
  clarification_options: string[];
  turn_type: string;
  retry_count: number;
}

export interface QueryStageEvent {
  type: 'stage';
  stage: 'understanding' | 'generating_sql' | 'running_query' | 'interpreting';
  label: string;
  progress: number;
}

@Injectable({
  providedIn: 'root'
})
export class ChatService {
  private apiUrl = getRuntimeApiUrl();
  private sessionKeyPrefix = 'qw_chat_session_id:';

  messages = signal<ChatMessage[]>([]);
  isLoading = signal(false);
  pipelineStage = signal<QueryStageEvent | null>(null);
  connectionId = signal<string>('');
  sessionId = signal<string | null>(null);

  constructor(private router: Router) {}

  init(connectionId: string) {
    this.connectionId.set(connectionId);
    const storedSession = this.getStoredSession(connectionId);
    if (storedSession) {
      this.sessionId.set(storedSession);
    } else {
      this.createNewSession(connectionId);
    }
  }

  private getApiUrl(): string {
    return sessionStorage.getItem('qw_api_url') || this.apiUrl;
  }

  private getToken(): string {
    return sessionStorage.getItem('qw_auth_token') || '';
  }

  private getStoredSession(connectionId: string): string | null {
    return sessionStorage.getItem(this.sessionKeyPrefix + connectionId);
  }

  private setStoredSession(connectionId: string, sessionId: string) {
    sessionStorage.setItem(this.sessionKeyPrefix + connectionId, sessionId);
  }

  private clearStoredSession(connectionId: string) {
    sessionStorage.removeItem(this.sessionKeyPrefix + connectionId);
  }

  private async createNewSession(connectionId: string) {
    try {
      const res = await fetch(`${this.getApiUrl()}/api/v1/sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.getToken()}`
        },
        credentials: 'include',
        body: JSON.stringify({ connection_id: connectionId })
      });
      if (res.ok) {
        const data = await res.json();
        this.sessionId.set(data.id);
        this.setStoredSession(connectionId, data.id);
      }
    } catch (e) {
      console.error('Failed to create session', e);
    }
  }

  async sendMessage(content: string) {
    const connId = this.connectionId();
    const sessId = this.sessionId();
    if (!connId || !sessId) return;

    const userMsg: ChatMessage = {
      id: `${Date.now()}-user`,
      role: 'user',
      content
    };
    this.messages.update(msgs => [...msgs, userMsg]);

    this.isLoading.set(true);
    this.pipelineStage.set(null);

    try {
      const response = await fetch(`${this.getApiUrl()}/api/v1/query/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.getToken()}`
        },
        credentials: 'include',
        body: JSON.stringify({
          connection_id: connId,
          question: content,
          session_id: sessId
        })
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(errorBody.error || `Request failed with status ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalResult: QueryResult | null = null;

      if (!reader) {
        throw new Error('No response body');
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop() || '';

        for (const chunk of chunks) {
          if (!chunk.trim() || !chunk.startsWith('data:')) continue;
          const eventData = chunk.slice(5).trim();
          if (!eventData) continue;

          try {
            const event = JSON.parse(eventData);
            if (event.type === 'stage') {
              this.pipelineStage.set(event);
            } else if (event.type === 'result') {
              finalResult = event.data;
            } else if (event.type === 'error') {
              throw new Error(event.message);
            }
          } catch {}
        }
      }

      if (finalResult) {
        const assistantMsg: ChatMessage = {
          id: `${Date.now()}-assistant`,
          role: 'assistant',
          result: finalResult
        };
        this.messages.update(msgs => [...msgs, assistantMsg]);
      }
    } catch (e: unknown) {
      const errorMsg = e instanceof Error ? e.message : 'An unexpected error occurred';
      const errorMsgBubble: ChatMessage = {
        id: `${Date.now()}-error`,
        role: 'error',
        errorMessage: errorMsg
      };
      this.messages.update(msgs => [...msgs, errorMsgBubble]);
    } finally {
      this.isLoading.set(false);
      this.pipelineStage.set(null);
    }
  }

  async resetChat() {
    const connId = this.connectionId();
    if (!connId) return;

    this.messages.set([]);
    this.clearStoredSession(connId);
    await this.createNewSession(connId);
  }

  loadRecentQuestions(): string[] {
    try {
      const token = this.getToken();
      if (!token) return [];
      const payload = token.split('.')[1];
      if (!payload) return [];
      const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
      const claims = JSON.parse(json);
      const userId = claims.sub;
      const key = userId ? `qw_recent_questions_${userId}` : 'qw_recent_questions';
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  saveRecentQuestion(question: string) {
    try {
      const token = this.getToken();
      if (!token) return;
      const payload = token.split('.')[1];
      if (!payload) return;
      const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
      const claims = JSON.parse(json);
      const userId = claims.sub;
      const key = userId ? `qw_recent_questions_${userId}` : 'qw_recent_questions';
      const raw = localStorage.getItem(key);
      const existing: string[] = raw ? JSON.parse(raw) : [];
      const deduped = existing.filter(q => q !== question);
      const next = [question, ...deduped].slice(0, 3);
      localStorage.setItem(key, JSON.stringify(next));
    } catch {}
  }
}