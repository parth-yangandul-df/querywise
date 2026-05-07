declare global {
  interface Window {
    __QW_API_URL__?: string;
  }
}

export function getRuntimeApiUrl(): string {
  const fromSession = sessionStorage.getItem('qw_api_url');
  if (fromSession) return fromSession;

  const fromWindow = window.__QW_API_URL__;
  if (fromWindow) return fromWindow;

  return 'http://localhost:8000';
}
