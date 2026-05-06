import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { API_BASE } from './api/client.ts'

// ── Auth state tracked before React mounts ─────────────────────────────────────
// 'pending' → showing splash while cookie exchange is in flight
// 'ok'      → exchange succeeded (or no token was provided — proceed normally)
// 'error'   → exchange failed — show error screen instead of the React app
type AuthState = 'pending' | 'ok' | 'error'

// ── Splash / error screens (pure HTML injected before React mounts) ────────────
const rootEl = document.getElementById('root')!

function showSplash(): void {
  rootEl.innerHTML = `
    <div class="flex flex-col items-center justify-center min-h-screen bg-background">
      <h1 class="text-2xl font-semibold text-foreground tracking-tight">QueryWise</h1>
      <div class="mt-4 h-1.5 w-8 rounded-full bg-primary animate-pulse"></div>
    </div>
  `
}

function showError(): void {
  rootEl.innerHTML = `
    <div class="flex flex-col items-center justify-center min-h-screen bg-background px-6">
      <h1 class="text-2xl font-semibold text-foreground tracking-tight">QueryWise</h1>
      <p class="mt-4 text-sm text-muted-foreground text-center max-w-sm">
        Session setup failed. Please close this tab and try again from the main application.
      </p>
    </div>
  `
}

// ── Token + connection handoff ─────────────────────────────────────────────────
// Angular passes ?token=<jwt>&connection_id=<uuid>&api_url=<url> when opening
// this page in a new tab. We exchange the token for an HttpOnly cookie session
// via POST /auth/cookie, then clean both params from the URL.
async function bootstrap(): Promise<void> {
  const params = new URLSearchParams(window.location.search)
  const tokenParam = params.get('token')
  const connectionIdParam = params.get('connection_id')
  const apiUrlParam = params.get('api_url')

  if (apiUrlParam) {
    sessionStorage.setItem('qw_api_url', apiUrlParam)
  }
  if (connectionIdParam) {
    sessionStorage.setItem('qw_connection_id', connectionIdParam)
  }

  // Determine auth state: exchange the JWT for an HttpOnly cookie BEFORE
  // React mounts, so the first API call already has the auth cookie available.
  let authState: AuthState = 'ok'

  if (tokenParam) {
    authState = 'pending'
    showSplash()

    const resolvedApiBase =
      apiUrlParam || sessionStorage.getItem('qw_api_url') || API_BASE

    try {
      const response = await fetch(`${resolvedApiBase}/api/v1/auth/cookie`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ token: tokenParam }),
      })

      authState = response.ok ? 'ok' : 'error'
    } catch {
      authState = 'error'
    }
  }

  if (tokenParam || connectionIdParam || apiUrlParam) {
    // Clean all handoff params from the URL so they aren't visible or bookmarked
    const cleanUrl = window.location.pathname + window.location.hash
    window.history.replaceState({}, '', cleanUrl)
  }

  // Auth failed — show error screen and stop (no React mount)
  if (authState === 'error') {
    showError()
    return
  }

  // Auth succeeded (or no token needed) — mount the React app
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 30_000,
      },
    },
  })

  createRoot(rootEl).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}

void bootstrap()