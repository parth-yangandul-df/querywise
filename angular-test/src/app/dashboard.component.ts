import { Component, OnInit, signal } from '@angular/core';
import { Router } from '@angular/router';

import { getRuntimeApiUrl } from './utils/api';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

interface Connection {
  id: string;
  name: string;
  connector_type: string;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page" [class.dark]="isDark()">
      <!-- Top bar -->
      <header class="topbar">
        <div class="brand">
          <div class="logo">QW</div>
          <span class="brand-name">QueryWise</span>
        </div>
        <div class="user-info">
          <div class="user-meta">
            <span class="user-email">{{ userEmail }}</span>
            <span class="badge" [class]="'badge-' + userRole">{{ userRole }}</span>
          </div>
          <button class="btn-theme" (click)="toggleTheme()" aria-label="Toggle theme">
            <span class="theme-icon">{{ isDark() ? '☀️' : '🌙' }}</span>
          </button>
          <button class="btn-open-chat" (click)="openQueryWiseChat()">Open QueryWise Chat</button>
          <button class="btn-logout" (click)="logout()">Sign out</button>
        </div>
      </header>

        <!-- Main content -->
      <main class="content">
        @if (loadingConnections()) {
          <div class="state-msg">Loading connections…</div>
        } @else if (connections().length === 0) {
          <div class="state-msg warn">
            No connections found. Create one in the
            <a href="http://localhost:5173/connections" target="_blank">QueryWise admin UI</a>
            first.
          </div>
        } @else {
          <div class="conn-info">
            @if (connections().length > 1) {
              <div class="conn-picker">
                <label for="conn-select">Connection</label>
                <select id="conn-select" [(ngModel)]="connectionId">
                  @for (c of connections(); track c.id) {
                    <option [value]="c.id">{{ c.name }} ({{ c.connector_type }})</option>
                  }
                </select>
              </div>
            }
            <p class="conn-name" *ngIf="connections().length === 1">
              Connected to <strong>{{ connections()[0]?.name }}</strong> ({{ connections()[0]?.connector_type }})
            </p>
            <button class="btn-open-chat" (click)="openQueryWiseChat()">
              Open QueryWise Chat
            </button>
            <a class="admin-link" href="http://localhost:5173/connections" target="_blank">
              Manage connections in admin UI →
            </a>
          </div>
        }
      </main>
    </div>
  `,
  styles: [`
    .page {
      min-height: 100vh;
      background: var(--bg-page);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex;
      flex-direction: column;
      transition: background-color 0.2s ease;
    }

    /* Top bar */
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      height: 56px;
      background: var(--bg-topbar);
      border-bottom: 1px solid var(--border-color);
      position: sticky;
      top: 0;
      z-index: 10;
      transition: background-color 0.2s ease, border-color 0.2s ease;
    }

    .brand { display: flex; align-items: center; gap: 10px; }
    .logo {
      width: 32px; height: 32px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      border-radius: 8px;
      color: #fff;
      font-size: .75rem;
      font-weight: 700;
      display: flex; align-items: center; justify-content: center;
    }
    .brand-name { font-weight: 700; font-size: 1rem; color: var(--text-primary); }

    .user-info { display: flex; align-items: center; gap: 14px; }
    .user-meta { display: flex; align-items: center; gap: 8px; }
    .user-email { font-size: .85rem; color: var(--text-secondary); }

    .badge {
      display: inline-block;
      border-radius: 20px;
      padding: 2px 10px;
      font-size: .72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .badge-admin   { background: var(--badge-admin-bg); color: var(--badge-admin-text); }
    .badge-manager { background: var(--badge-manager-bg); color: var(--badge-manager-text); }
    .badge-user    { background: var(--badge-user-bg); color: var(--badge-user-text); }

    .btn-theme {
      padding: 6px 10px;
      border: 1.5px solid var(--border-color);
      border-radius: 8px;
      background: var(--btn-logout-bg);
      cursor: pointer;
      transition: all .15s;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .btn-theme:hover { border-color: var(--btn-logout-hover-border); }
    .theme-icon { font-size: 1rem; }

    .btn-logout {
      padding: 6px 14px;
      border: 1.5px solid var(--btn-logout-border);
      border-radius: 8px;
      background: var(--btn-logout-bg);
      color: var(--btn-logout-text);
      font-size: .85rem;
      font-weight: 500;
      cursor: pointer;
      transition: all .15s;
    }
    .btn-logout:hover { border-color: var(--btn-logout-hover-border); color: var(--btn-logout-hover-text); }

    .btn-open-chat {
      padding: 6px 14px;
      border: 1.5px solid var(--btn-chat-bg);
      border-radius: 8px;
      background: var(--btn-chat-bg);
      color: var(--btn-chat-text);
      font-size: .85rem;
      font-weight: 500;
      cursor: pointer;
      transition: all .15s;
    }
    .btn-open-chat:hover { background: var(--btn-chat-hover-bg); border-color: var(--btn-chat-hover-border); }

    /* Content */
    .content { padding: 32px 24px; max-width: 900px; margin: 0 auto; width: 100%; box-sizing: border-box; }

    .state-msg {
      padding: 16px 20px;
      border-radius: 10px;
      font-size: .875rem;
      color: var(--state-msg-text);
      background: var(--state-msg-bg);
      margin-bottom: 20px;
    }
    .state-msg.warn {
      background: var(--state-msg-warn-bg);
      color: var(--state-msg-warn-text);
      border: 1px solid var(--state-msg-warn-border);
    }
    .state-msg a { color: #6366f1; }

    /* Connection info */
    .conn-info {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 20px;
      padding: 48px 24px;
      text-align: center;
    }
    .conn-name {
      font-size: .9rem;
      color: var(--conn-name-text);
    }
    .conn-name strong {
      color: var(--conn-name-strong);
    }
    .admin-link {
      font-size: .8rem;
      color: #6366f1;
      text-decoration: none;
    }
    .admin-link:hover { text-decoration: underline; }

    /* Connection picker */
    .conn-picker {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 20px;
    }
    .conn-picker label { font-size: .85rem; font-weight: 600; color: var(--text-primary); white-space: nowrap; }
    .conn-picker select {
      padding: 7px 10px;
      border: 1.5px solid var(--select-border);
      border-radius: 8px;
      font-size: .875rem;
      color: var(--select-text);
      background: var(--select-bg);
      cursor: pointer;
      outline: none;
    }
    .conn-picker select:focus { border-color: #6366f1; }
  `],
})
export class DashboardComponent implements OnInit {
  connectionId = '';
  userEmail = '';
  userRole = '';

  isDark = signal(false);
  connections = signal<Connection[]>([]);
  loadingConnections = signal(true);

  constructor(private router: Router) {
    const stored = localStorage.getItem('qw_theme');
    const dark = stored === 'dark';
    this.isDark.set(dark);
    document.documentElement.classList.toggle('dark', dark);
  }

  toggleTheme() {
    this.isDark.update((v) => !v);
    const dark = this.isDark();
    localStorage.setItem('qw_theme', dark ? 'dark' : 'light');
    document.documentElement.classList.toggle('dark', dark);
  }

  get roleIcon() {
    return ({ admin: '🔑', manager: '📊', user: '👤' } as Record<string, string>)[this.userRole] ?? '👤';
  }
  get roleLabel() {
    return ({ admin: 'Administrator', manager: 'Manager', user: 'Standard User' } as Record<string, string>)[this.userRole] ?? this.userRole;
  }
  get roleDescription() {
    return ({
      admin:   'Full access — can query all data, manage connections, and edit all metadata.',
      manager: 'Read access — can query all data and view metadata, but cannot make changes.',
      user:    'Scoped access — queries are automatically filtered to your own data only.',
    } as Record<string, string>)[this.userRole] ?? '';
  }

  async ngOnInit() {
    this.userEmail = sessionStorage.getItem('qw_user_email') ?? '';
    this.userRole  = sessionStorage.getItem('qw_user_role')  ?? '';
    await this.loadConnections();
  }

  private async loadConnections() {
    const apiUrl = getRuntimeApiUrl();
    const token  = sessionStorage.getItem('qw_auth_token') ?? '';
    try {
      const res = await fetch(`${apiUrl}/api/v1/connections`, {
        headers: { Authorization: `Bearer ${token}` },
        credentials: 'include',
      });
      if (res.ok) {
        const data: Connection[] = await res.json();
        this.connections.set(data);
        if (data.length > 0) this.connectionId = data[0].id;
      }
    } catch {
      // leave connections empty — template shows the warning
    } finally {
      this.loadingConnections.set(false);
    }
  }

  logout() {
    // Clear all chat session keys
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      if (key && key.startsWith('qw_chat_session_id:')) {
        sessionStorage.removeItem(key);
      }
    }
    sessionStorage.removeItem('qw_auth_token');
    sessionStorage.removeItem('qw_api_url');
    sessionStorage.removeItem('qw_user_role');
    sessionStorage.removeItem('qw_user_email');
    this.router.navigate(['/login']);
  }

  openQueryWiseChat() {
    this.router.navigate(['/chat'], { queryParams: { connection_id: this.connectionId } });
  }
}