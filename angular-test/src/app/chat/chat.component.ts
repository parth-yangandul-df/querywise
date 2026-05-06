import { Component, OnInit, signal, ElementRef, ViewChild, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ChatService, type ChatMessage, type QueryResult } from '../services/chat.service';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chat.component.html',
  styleUrls: ['./chat.component.css']
})
export class ChatComponent implements OnInit {
  @ViewChild('messagesContainer') messagesContainer!: ElementRef<HTMLDivElement>;
  @ViewChild('inputField') inputField!: ElementRef<HTMLTextAreaElement>;

  input = '';
  messages = signal<ChatMessage[]>([]);
  isLoading = signal(false);
  pipelineStage = signal<{ stage: string; label: string; progress: number } | null>(null);
  connectionId = signal<string>('');
  recentQuestions = signal<string[]>([]);
  sqlExpanded = signal<Record<string, boolean>>({});
  copiedSql = signal<string | null>(null);

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    public chatService: ChatService
  ) {
    effect(() => {
      this.messages.set(this.chatService.messages());
      this.isLoading.set(this.chatService.isLoading());
      this.pipelineStage.set(this.chatService.pipelineStage());
    });
  }

  ngOnInit() {
    const connId = this.route.snapshot.queryParamMap.get('connection_id');
    if (!connId) {
      this.router.navigate(['/']);
      return;
    }
    this.connectionId.set(connId);
    this.chatService.init(connId);
    this.recentQuestions.set(this.chatService.loadRecentQuestions());
  }

  async sendMessage() {
    if (!this.input.trim() || this.isLoading()) return;
    const content = this.input.trim();
    this.chatService.saveRecentQuestion(content);
    this.input = '';
    await this.chatService.sendMessage(content);
    setTimeout(() => this.scrollToBottom(), 50);
  }

  onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  scrollToBottom() {
    if (this.messagesContainer) {
      this.messagesContainer.nativeElement.scrollTop = this.messagesContainer.nativeElement.scrollHeight;
    }
  }

  toggleSql(id: string) {
    this.sqlExpanded.update(e => ({ ...e, [id]: !e[id] }));
  }

  copySql(sql: string, id: string) {
    navigator.clipboard.writeText(sql);
    this.copiedSql.set(id);
    setTimeout(() => this.copiedSql.set(null), 2000);
  }

  selectRecentQuestion(q: string) {
    this.input = q;
    this.inputField?.nativeElement.focus();
  }

  async resetChat() {
    await this.chatService.resetChat();
    this.recentQuestions.set(this.chatService.loadRecentQuestions());
  }

  getStageLabel(stage: string): string {
    const labels: Record<string, string> = {
      'understanding': 'Understanding your question...',
      'generating_sql': 'Generating SQL...',
      'running_query': 'Running query...',
      'interpreting': 'Interpreting results...'
    };
    return labels[stage] || stage;
  }

  trackByMessage(index: number, msg: ChatMessage): string {
    return msg.id;
  }
}