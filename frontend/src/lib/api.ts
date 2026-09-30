export type FieldError = { field: string; message: string }
export type Tenant = { id: string; slug: string; name: string; role?: string }
export type SessionUser = { id: string; name: string; email: string; role: string; permissions: string[] }
export type Session = { access_token: string; expires_in: number; user: SessionUser; tenant: Tenant; tenants: Tenant[] }
type Body = RequestInit & { json?: unknown }

export class ApiError extends Error {
  status: number
  code: string
  fields: FieldError[]
  details: unknown
  requestId: string

  constructor(status: number, body: unknown) {
    const error = (body as { error?: Record<string, unknown> } | null)?.error ?? {}
    super(typeof error.message === 'string' ? error.message : status >= 500 ? 'The service is temporarily unavailable. Please try again.' : 'Request failed.')
    this.status = status
    this.code = typeof error.code === 'string' ? error.code : 'request_failed'
    this.fields = Array.isArray(error.fields) ? (error.fields as FieldError[]) : []
    this.details = error.details ?? null
    this.requestId = typeof error.request_id === 'string' ? error.request_id : ''
  }
}

let accessToken: string | null = null
let refreshing: Promise<Session | null> | null = null
let handlers = { session: (_: Session | null) => {}, expired: () => {} }

export function setAuthHandlers(session: (value: Session | null) => void, expired: () => void) {
  handlers = { session, expired }
}

export function setAccessToken(session: Session | null) {
  accessToken = session?.access_token ?? null
}

function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)campus_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

/** Single-flight refresh so concurrent 401s never replay (and thereby revoke) the rotating refresh token. */
export function refreshSession(): Promise<Session | null> {
  if (!refreshing) {
    refreshing = fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': csrfToken() } })
      .then(async (response) => (response.ok ? ((await response.json()) as Session) : null))
      .catch(() => null)
      .then((session) => {
        accessToken = session?.access_token ?? null
        if (session) handlers.session(session)
        return session
      })
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

async function send(path: string, init: Body) {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  let body = init.body
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(init.json)
  }
  return fetch(path, { ...init, headers, body, credentials: 'same-origin' })
}

export async function request(path: string, init: Body = {}, retried = false): Promise<Response> {
  const response = await send(path, init)
  if (response.status === 401 && !retried && !path.startsWith('/api/v1/auth/login')) {
    if (await refreshSession()) return request(path, init, true)
    handlers.expired()
  }
  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    throw new ApiError(response.status, body)
  }
  return response
}

export async function api<T = any>(path: string, init: Body = {}): Promise<T> {
  const response = await request(path, init)
  return (response.status === 204 ? undefined : await response.json()) as T
}

export const get = <T = any>(path: string) => api<T>(path)
export const post = <T = any>(path: string, json: unknown = {}) => api<T>(path, { method: 'POST', json })
export const put = <T = any>(path: string, json: unknown) => api<T>(path, { method: 'PUT', json })
export const patch = <T = any>(path: string, json: unknown) => api<T>(path, { method: 'PATCH', json })
export const del = (path: string) => api<void>(path, { method: 'DELETE' })

export async function download(path: string, fallback: string) {
  const response = await request(path)
  const blob = await response.blob()
  const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? fallback
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    const reference = error.status >= 500 && error.requestId ? ` (reference ${error.requestId.slice(0, 8)})` : ''
    if (error.status === 429 && !error.message) return 'Too many requests. Please wait a moment and try again.'
    return error.message + reference
  }
  if (error instanceof TypeError) return 'Cannot reach the server. Check your connection and try again.'
  return error instanceof Error ? error.message : 'Something went wrong.'
}

export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {}
  return Object.fromEntries(error.fields.map((item) => [item.field.split('.').slice(-1)[0], item.message]))
}

export function qs(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '' && value !== false) search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export function idempotencyKey() {
  return typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}
