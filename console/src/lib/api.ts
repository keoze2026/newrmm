const BASE = '/api'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

let authToken: string | null = null

export function setToken(token: string | null) {
  authToken = token
  if (token) sessionStorage.setItem('rdp_token', token)
  else sessionStorage.removeItem('rdp_token')
}

export function loadToken(): string | null {
  authToken = sessionStorage.getItem('rdp_token')
  return authToken
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (authToken) headers.set('Authorization', `Bearer ${authToken}`)

  const response = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export interface Operator {
  id: string
  email: string
  full_name: string
  role: string
  is_active: boolean
  last_login_at: string | null
}

export interface Session {
  id: string
  code: string
  mode: 'attended' | 'unattended'
  state: 'pending' | 'active' | 'ended'
  operator_id: string
  device_id: string | null
  created_at: string
  started_at: string | null
  ended_at: string | null
}

export interface Device {
  id: string
  name: string
  os: 'windows' | 'macos' | 'linux'
  status: 'online' | 'offline'
  enrolled_at: string
  last_seen_at: string | null
}

export interface AuditEvent {
  id: number
  ts: string
  actor_type: string
  actor_id: string | null
  actor_label: string
  action: string
  target_type: string | null
  target_id: string | null
  ip: string | null
  detail: Record<string, unknown>
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; expires_in: number }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<Operator>('/auth/me'),
  listSessions: () => request<Session[]>('/sessions'),
  createSession: (mode: 'attended' | 'unattended', deviceId?: string) =>
    request<Session>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ mode, device_id: deviceId ?? null }),
    }),
  updateSessionState: (id: string, state: 'active' | 'ended') =>
    request<Session>(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify({ state }) }),
  listDevices: () => request<Device[]>('/devices'),
  enrollDevice: (name: string, os: Device['os']) =>
    request<Device & { enrollment_secret: string }>('/devices', {
      method: 'POST',
      body: JSON.stringify({ name, os }),
    }),
  listAudit: () => request<AuditEvent[]>('/audit'),
  health: () => request<{ status: string; checks: Record<string, string> }>('/health'),
}
