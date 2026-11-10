import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Legacy components call http://127.0.0.1:8000 or the current hostname on :8000.
// During local Vite development, preserve the direct FastAPI connection.
// When served by Caddy, put *all* API requests under /api/ to avoid collisions
// between React routes (/stocks, /analytics, ...) and FastAPI endpoints.
const LOCAL_VITE_DEV = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  && window.location.port === '5173'
const API_BASE = LOCAL_VITE_DEV
  ? `${window.location.protocol}//${window.location.hostname}:8000`
  : `${window.location.origin}/api`

const nativeFetch = window.fetch.bind(window)

window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  const rawUrl = typeof input === 'string'
    ? input
    : input instanceof URL ? input.toString() : input.url

  let parsed: URL
  try {
    parsed = new URL(rawUrl, window.location.origin)
  } catch {
    return nativeFetch(input, init)
  }

  const legacyBackend = parsed.port === '8000'
    && ['localhost', '127.0.0.1', window.location.hostname].includes(parsed.hostname)
    && (parsed.protocol === 'http:' || parsed.protocol === 'https:')

  if (!legacyBackend) return nativeFetch(input, init)

  const destination = `${API_BASE}${parsed.pathname}${parsed.search}${parsed.hash}`
  const adjustedInput = input instanceof Request
    ? new Request(destination, input)
    : destination

  return nativeFetch(adjustedInput, {
    ...init,
    credentials: 'include',
  }).then(response => {
    if (response.status === 401 && !parsed.pathname.startsWith('/auth/')) {
      window.dispatchEvent(new Event('marketplace-auth-expired'))
    }
    return response
  })
}) as typeof window.fetch

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
