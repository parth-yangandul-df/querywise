import axios from 'axios';

import { clearUserInfo } from '../utils/auth';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/** Read a cookie value by name from document.cookie (non-HttpOnly cookies only). */
function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
  // Send HttpOnly cookies automatically on every request
  withCredentials: true,
});

// Attach CSRF token header on every mutating request
api.interceptors.request.use((config) => {
  const csrfToken = getCookie('csrf_token');
  if (csrfToken) {
    config.headers['X-CSRF-Token'] = csrfToken;
  }
  return config;
});

// Surface real backend error messages; redirect to /login on 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Only redirect on 401 for non-auth endpoints — let LoginPage handle its own 401s
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      clearUserInfo();
      window.location.href = '/login';
      return Promise.reject(error);
    }
    // FastAPI returns errors in 'detail', not 'error'
    if (error.response?.data?.detail) {
      error.message = error.response.data.detail;
    } else if (error.response?.data?.error) {
      error.message = error.response.data.error;
    }
    return Promise.reject(error);
  },
);
