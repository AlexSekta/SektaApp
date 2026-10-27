import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// All application API requests use the session cookie.
// localhost и 127.0.0.1 считаются разными cookie-host.
// Поэтому локальный backend всегда приводим к hostname, с которого открыт frontend.
const LOCAL_BACKEND_127 = "http://127.0.0.1:8000";
const LOCAL_BACKEND_LOCALHOST = "http://localhost:8000";
const API_ORIGIN = `${window.location.protocol}//${window.location.hostname}:8000`;

const nativeFetch = window.fetch.bind(window);

window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  let url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;

  const isLocalBackend =
    url.startsWith(LOCAL_BACKEND_127) ||
    url.startsWith(LOCAL_BACKEND_LOCALHOST);

  if (!isLocalBackend) {
    return nativeFetch(input, init);
  }

  const oldOrigin = url.startsWith(LOCAL_BACKEND_127)
    ? LOCAL_BACKEND_127
    : LOCAL_BACKEND_LOCALHOST;

  const normalizedUrl =
    API_ORIGIN + url.slice(oldOrigin.length);

  return nativeFetch(normalizedUrl, {
    ...(init || {}),
    credentials: "include",
  }).then((response) => {
    if (
      response.status === 401 &&
      !normalizedUrl.startsWith(`${API_ORIGIN}/auth/`)
    ) {
      window.dispatchEvent(new Event("marketplace-auth-expired"));
    }
    return response;
  });
}) as typeof window.fetch;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
