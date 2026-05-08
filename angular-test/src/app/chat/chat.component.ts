import { Component, OnInit, signal, ElementRef, ViewChild, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ChatService, type ChatMessage, type QueryResult } from '../services/chat.service';

interface TableState {
  searchTerm: string;
  currentPage: number;
  rowsPerPage: number;
  sortField: string;
  sortOrder: 1 | -1 | null;
}

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

  tableStates = signal<Record<string, TableState>>({});

  rowsPerPageOptions = [
    { label: '10', value: 10 },
    { label: '25', value: 25 },
    { label: '50', value: 50 },
  ];

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    public chatService: ChatService
  ) {
    effect(() => {
      const msgs = this.chatService.messages();
      this.messages.set(msgs);
      this.isLoading.set(this.chatService.isLoading());
      this.pipelineStage.set(this.chatService.pipelineStage());
      this.initializeTableStates(msgs);
    });
  }

  private initializeTableStates(messages: ChatMessage[]) {
    const currentStates = this.tableStates();
    let hasChanges = false;
    const newStates = { ...currentStates };

    for (const msg of messages) {
      if (msg.role === 'assistant' && msg.result) {
        const resultId = msg.result.id;
        if (!newStates[resultId]) {
          newStates[resultId] = {
            searchTerm: '',
            currentPage: 1,
            rowsPerPage: 10,
            sortField: '',
            sortOrder: null,
          };
          hasChanges = true;
        }
      }
    }

    if (hasChanges) {
      this.tableStates.set(newStates);
    }
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

  getTableState(resultId: string): TableState {
    const states = this.tableStates();
    if (!states[resultId]) {
      this.tableStates.update(s => ({
        ...s,
        [resultId]: {
          searchTerm: '',
          currentPage: 1,
          rowsPerPage: 10,
          sortField: '',
          sortOrder: null,
        }
      }));
    }
    return this.tableStates()[resultId];
  }

  updateTableState(resultId: string, update: Partial<TableState>) {
    this.tableStates.update(s => ({
      ...s,
      [resultId]: { ...s[resultId], ...update }
    }));
  }

  getFilteredRows(result: QueryResult): unknown[][] {
    const state = this.getTableState(result.id);
    if (!state.searchTerm.trim()) return result.rows;

    const term = state.searchTerm.toLowerCase();
    return result.rows.filter(row =>
      row.some(cell => cell !== null && cell !== undefined && String(cell).toLowerCase().includes(term))
    );
  }

  getSortedRows(rows: unknown[][], result: QueryResult): unknown[][] {
    const state = this.getTableState(result.id);
    if (!state.sortField || state.sortOrder === null) return rows;

    const colIndex = result.columns.indexOf(state.sortField);
    if (colIndex === -1) return rows;

    return [...rows].sort((a, b) => {
      const aVal = a[colIndex];
      const bVal = b[colIndex];

      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      let comparison = 0;
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        comparison = aVal - bVal;
      } else {
        comparison = String(aVal).localeCompare(String(bVal));
      }

      return state.sortOrder === 1 ? comparison : -comparison;
    });
  }

  getPaginatedRows(result: QueryResult): { rows: unknown[][], total: number } {
    const state = this.getTableState(result.id);
    const filtered = this.getFilteredRows(result);
    const sorted = this.getSortedRows(filtered, result);

    const start = (state.currentPage - 1) * state.rowsPerPage;
    const end = start + state.rowsPerPage;
    const paginatedRows = sorted.slice(start, end);

    return { rows: paginatedRows, total: sorted.length };
  }

  onSort(resultId: string, field: string) {
    const state = this.getTableState(resultId);
    let newOrder: 1 | -1 | null = 1;

    if (state.sortField === field) {
      if (state.sortOrder === 1) newOrder = -1;
      else if (state.sortOrder === -1) newOrder = null;
      else newOrder = 1;
    }

    this.updateTableState(resultId, {
      sortField: newOrder ? field : '',
      sortOrder: newOrder,
      currentPage: 1,
    });
  }

  onSearchChange(resultId: string, term: string) {
    this.updateTableState(resultId, {
      searchTerm: term,
      currentPage: 1,
    });
  }

  onPageChange(resultId: string, page: number) {
    this.updateTableState(resultId, { currentPage: page });
  }

  onRowsPerPageChange(resultId: string, rows: number) {
    this.updateTableState(resultId, {
      rowsPerPage: rows,
      currentPage: 1,
    });
  }

  exportToCsv(result: QueryResult) {
    const filtered = this.getFilteredRows(result);
    const sorted = this.getSortedRows(filtered, result);

    const escapeValue = (val: unknown): string => {
      if (val === null || val === undefined) return '';
      const str = String(val);
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };

    const header = result.columns.map(escapeValue).join(',');
    const rows = sorted.map(row => row.map(escapeValue).join(',')).join('\n');
    const csv = `${header}\n${rows}`;

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `query_result_${result.id}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  formatCellValue(value: unknown, columnType: string): string {
    if (value === null || value === undefined) return '';

    if (columnType === 'timestamp' || columnType === 'date') {
      if (value instanceof Date) return value.toLocaleDateString();
      if (typeof value === 'string') {
        const d = new Date(value);
        if (!isNaN(d.getTime())) return d.toLocaleDateString();
      }
    }

    if (columnType === 'numeric' || columnType === 'decimal' || columnType === 'float8') {
      if (typeof value === 'number') return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }

    if (columnType === 'money' || columnType === 'currency') {
      if (typeof value === 'number') return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
    }

    return String(value);
  }

  getSortIcon(resultId: string, field: string): string {
    const state = this.getTableState(resultId);
    if (state.sortField !== field) return 'pi pi-sort-alt';
    return state.sortOrder === 1 ? 'pi pi-sort-amount-up' : state.sortOrder === -1 ? 'pi pi-sort-amount-down' : 'pi pi-sort-alt';
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
    this.tableStates.set({});
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

  getTotalPages(result: QueryResult): number {
    const total = this.getPaginatedRows(result).total;
    const rows = this.getTableState(result.id).rowsPerPage;
    return Math.ceil(total / rows);
  }

  getVisiblePages(result: QueryResult): number[] {
    const total = this.getTotalPages(result);
    const current = this.getTableState(result.id).currentPage;
    const pages: number[] = [];
    const maxVisible = 5;

    if (total <= maxVisible) {
      for (let i = 1; i <= total; i++) pages.push(i);
    } else {
      let start = Math.max(1, current - 2);
      let end = Math.min(total, start + maxVisible - 1);
      if (end - start < maxVisible - 1) start = Math.max(1, end - maxVisible + 1);
      for (let i = start; i <= end; i++) pages.push(i);
    }
    return pages;
  }

  min(a: number, b: number): number {
    return Math.min(a, b);
  }
}