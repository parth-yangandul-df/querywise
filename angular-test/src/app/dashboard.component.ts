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
    <div class="page">
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
      background: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex;
      flex-direction: column;
    }

    /* Top bar */
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      height: 56px;
      background: #fff;
      border-bottom: 1px solid #e2e8f0;
      position: sticky;
      top: 0;
      z-index: 10;
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
    .brand-name { font-weight: 700; font-size: 1rem; color: #1e293b; }

    .user-info { display: flex; align-items: center; gap: 14px; }
    .user-meta { display: flex; align-items: center; gap: 8px; }
    .user-email { font-size: .85rem; color: #64748b; }

    .badge {
      display: inline-block;
      border-radius: 20px;
      padding: 2px 10px;
      font-size: .72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .badge-admin   { background: #e0e7ff; color: #4338ca; }
    .badge-manager { background: #fef9c3; color: #92400e; }
    .badge-user    { background: #dcfce7; color: #166534; }

    .btn-logout {
      padding: 6px 14px;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      background: #fff;
      color: #64748b;
      font-size: .85rem;
      font-weight: 500;
      cursor: pointer;
      transition: all .15s;
    }
    .btn-logout:hover { border-color: #cbd5e1; color: #1e293b; }

    .btn-open-chat {
      padding: 6px 14px;
      border: 1.5px solid #1e293b;
      border-radius: 8px;
      background: #1e293b;
      color: #fff;
      font-size: .85rem;
      font-weight: 500;
      cursor: pointer;
      transition: all .15s;
    }
    .btn-open-chat:hover { background: #334155; border-color: #334155; }

    /* Content */
    .content { padding: 32px 24px; max-width: 900px; margin: 0 auto; width: 100%; box-sizing: border-box; }

    .state-msg {
      padding: 16px 20px;
      border-radius: 10px;
      font-size: .875rem;
      color: #64748b;
      background: #f1f5f9;
      margin-bottom: 20px;
    }
    .state-msg.warn {
      background: #fefce8;
      color: #92400e;
      border: 1px solid #fde68a;
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
      color: #64748b;
    }
    .conn-name strong {
      color: #1e293b;
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
    .conn-picker label { font-size: .85rem; font-weight: 600; color: #374151; white-space: nowrap; }
    .conn-picker select {
      padding: 7px 10px;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      font-size: .875rem;
      color: #1e293b;
      background: #fff;
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

  connections = signal<Connection[]>([]);
  loadingConnections = signal(true);

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

  constructor(private router: Router) {}

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