import axios from 'axios'

export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export function getApiBaseUrl() {
  return sessionStorage.getItem('qw_api_url') || API_BASE
}

/** Read a cookie value by name (non-HttpOnly cookies only). */
function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

export const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
  // Send HttpOnly cookies automatically on every cross-origin request
  withCredentials: true,
})

// Widget: resolves base URL from sessionStorage on every request (Angular sets it before first call).
// Attaches CSRF token header for mutating requests.
api.interceptors.request.use((config) => {
  config.baseURL = `${getApiBaseUrl()}/api/v1`
  const csrfToken = getCookie('csrf_token')
  if (csrfToken) {
    config.headers['X-CSRF-Token'] = csrfToken
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      error &&
      typeof error === 'object' &&
      'response' in error &&
      error.response &&
      typeof error.response === 'object' &&
      'data' in error.response &&
      error.response.data &&
      typeof error.response.data === 'object' &&
      'error' in error.response.data
    ) {
      const err = error as { message: string; response: { data: { error: string } } }
      err.message = err.response.data.error
    }
    return Promise.reject(error)
  },
)
