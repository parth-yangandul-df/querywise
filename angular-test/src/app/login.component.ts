import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { getRuntimeApiUrl } from './utils/api';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, CommonModule],
  template: `
    <div class="page" [class.dark]="isDark()">
      <button class="theme-toggle" (click)="toggleTheme()" aria-label="Toggle theme">
        {{ isDark() ? '☀️' : '🌙' }}
      </button>
      <div class="card">
        <!-- Logo / title -->
        <div class="brand">
          <div class="logo">QW</div>
          <h1>QueryWise</h1>
          <p class="tagline">Sign in to continue</p>
        </div>

        <!-- Quick-fill buttons for demo -->
        <div class="quick-fill">
          <span class="quick-label">Quick fill:</span>
          <button type="button" class="chip chip-admin"   (click)="fill('admin@querywise.dev','admin123')">Admin</button>
          <button type="button" class="chip chip-manager" (click)="fill('manager@querywise.dev','manager123')">Manager</button>
          <button type="button" class="chip chip-user"    (click)="fill('user@querywise.dev','user123')">User</button>
        </div>

        <form (ngSubmit)="login()" #f="ngForm">
          <div class="field">
            <label for="email">Email</label>
            <input
              id="email"
              type="email"
              name="email"
              [(ngModel)]="email"
              required
              autocomplete="email"
              placeholder="you@example.com"
            />
          </div>

          <div class="field">
            <label for="password">Password</label>
            <input
              id="password"
              type="password"
              name="password"
              [(ngModel)]="password"
              required
              autocomplete="current-password"
              placeholder="••••••••"
            />
          </div>

          @if (error()) {
            <div class="error-banner">{{ error() }}</div>
          }

          <button type="submit" class="btn-primary" [disabled]="loading()">
            @if (loading()) { Signing in… } @else { Sign in }
          </button>
        </form>

        <!-- Seed credentials reference -->
        <details class="creds">
          <summary>Dev seed credentials</summary>
          <table>
            <thead><tr><th>Role</th><th>Email</th><th>Password</th></tr></thead>
            <tbody>
              <tr><td><span class="badge badge-admin">admin</span></td><td>admin&#64;querywise.dev</td><td>admin123</td></tr>
              <tr><td><span class="badge badge-manager">manager</span></td><td>manager&#64;querywise.dev</td><td>manager123</td></tr>
              <tr><td><span class="badge badge-user">user</span></td><td>user&#64;querywise.dev</td><td>user123</td></tr>
            </tbody>
          </table>
        </details>
      </div>
    </div>
  `,
  styles: [`
    .page {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, var(--bg-gradient-start) 0%, var(--bg-gradient-end) 100%);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      padding: 1rem;
      position: relative;
      transition: background 0.3s ease;
    }

    .theme-toggle {
      position: absolute;
      top: 20px;
      right: 20px;
      background: var(--card-bg);
      border: 1.5px solid var(--input-border);
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 1.2rem;
      cursor: pointer;
      transition: all .15s;
    }
    .theme-toggle:hover { border-color: var(--input-focus); }

    .card {
      background: var(--card-bg);
      border-radius: 16px;
      box-shadow: 0 4px 24px var(--card-shadow);
      padding: 40px 36px 32px;
      width: 100%;
      max-width: 400px;
      transition: background 0.3s ease, box-shadow 0.3s ease;
    }

    .brand { text-align: center; margin-bottom: 28px; }
    .logo {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 52px; height: 52px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      border-radius: 14px;
      color: #fff;
      font-size: 1.1rem;
      font-weight: 700;
      letter-spacing: .5px;
      margin-bottom: 12px;
    }
    h1 { margin: 0 0 4px; font-size: 1.4rem; color: var(--text-primary); font-weight: 700; }
    .tagline { margin: 0; color: var(--text-secondary); font-size: .875rem; }

    /* Quick fill */
    .quick-fill {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 22px;
      flex-wrap: wrap;
    }
    .quick-label { font-size: .75rem; color: var(--text-muted); white-space: nowrap; }
    .chip {
      border: none;
      border-radius: 20px;
      padding: 4px 12px;
      font-size: .78rem;
      font-weight: 600;
      cursor: pointer;
      transition: opacity .15s;
    }
    .chip:hover { opacity: .8; }
    .chip-admin   { background: #e0e7ff; color: #4338ca; }
    .chip-manager { background: #fef9c3; color: #92400e; }
    .chip-user    { background: #dcfce7; color: #166534; }

    .field { margin-bottom: 18px; }
    label {
      display: block;
      font-size: .8rem;
      font-weight: 600;
      color: var(--text-secondary);
      margin-bottom: 6px;
    }
    input {
      width: 100%;
      padding: 10px 12px;
      border: 1.5px solid var(--input-border);
      border-radius: 8px;
      font-size: .95rem;
      color: var(--text-primary);
      background: var(--card-bg);
      box-sizing: border-box;
      transition: border-color .15s;
      outline: none;
    }
    input:focus { border-color: var(--input-focus); box-shadow: 0 0 0 3px rgba(99,102,241,.12); }
    input::placeholder { color: var(--text-muted); }

    .error-banner {
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #dc2626;
      border-radius: 8px;
      padding: 10px 12px;
      font-size: .85rem;
      margin-bottom: 16px;
    }

    .btn-primary {
      width: 100%;
      padding: 11px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: opacity .15s;
    }
    .btn-primary:hover:not(:disabled) { opacity: .9; }
    .btn-primary:disabled { opacity: .6; cursor: not-allowed; }

    /* Creds table */
    .creds {
      margin-top: 24px;
      font-size: .8rem;
      color: var(--text-secondary);
    }
    summary { cursor: pointer; user-select: none; color: var(--text-muted); }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    th, td { text-align: left; padding: 5px 6px; border-bottom: 1px solid var(--table-border); }
    th { color: var(--text-muted); font-weight: 600; font-size: .75rem; }

    .badge {
      display: inline-block;
      border-radius: 20px;
      padding: 2px 8px;
      font-size: .72rem;
      font-weight: 700;
    }
    .badge-admin   { background: #e0e7ff; color: #4338ca; }
    .badge-manager { background: #fef9c3; color: #92400e; }
    .badge-user    { background: #dcfce7; color: #166534; }
  `],
})
export class LoginComponent {
  email = '';
  password = '';
  loading = signal(false);
  error = signal('');
  isDark = signal(false);

  constructor(private router: Router) {
    const stored = localStorage.getItem('qw_theme');
    const dark = stored === 'dark';
    this.isDark.set(dark);
    document.documentElement.classList.toggle('dark', dark);
  }

  toggleTheme() {
    this.isDark.update(v => !v);
    const dark = this.isDark();
    localStorage.setItem('qw_theme', dark ? 'dark' : 'light');
    document.documentElement.classList.toggle('dark', dark);
  }

  fill(email: string, password: string) {
    this.email = email;
    this.password = password;
    this.error.set('');
  }

  async login() {
    this.error.set('');
    this.loading.set(true);
    try {
      const apiBase = getRuntimeApiUrl();
      const res = await fetch(`${apiBase}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: this.email, password: this.password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        this.error.set(body?.detail ?? 'Invalid credentials');
        return;
      }
      const data = await res.json();
      sessionStorage.setItem('qw_api_url', apiBase);
      sessionStorage.setItem('qw_auth_token', data.access_token);
      sessionStorage.setItem('qw_user_role', data.role ?? '');
      sessionStorage.setItem('qw_user_email', data.email ?? this.email);
      this.router.navigate(['/']);
    } catch {
      this.error.set('Could not reach the server. Is the backend running?');
    } finally {
      this.loading.set(false);
    }
  }
}
