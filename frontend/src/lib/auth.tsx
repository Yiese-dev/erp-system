import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { post, refreshSession, setAccessToken, setAuthHandlers } from './api'
import type { Session } from './api'

type Status = 'loading' | 'anonymous' | 'authenticated'
type AuthValue = {
  status: Status
  session: Session | null
  notice: string
  login: (tenant: string, email: string, password: string) => Promise<void>
  logout: (notice?: string) => Promise<void>
  switchTenant: (tenantId: string) => Promise<void>
  can: (...permissions: string[]) => boolean
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const [status, setStatus] = useState<Status>('loading')
  const [session, setSession] = useState<Session | null>(null)
  const [notice, setNotice] = useState('')

  const adopt = useCallback((value: Session | null, message = '') => {
    setAccessToken(value)
    setSession(value)
    setStatus(value ? 'authenticated' : 'anonymous')
    setNotice(message)
  }, [])

  useEffect(() => {
    setAuthHandlers(
      (value) => { if (value) { setSession(value) } },
      () => { client.clear(); adopt(null, 'Your session has expired. Please sign in again.') },
    )
    refreshSession().then((value) => adopt(value))
  }, [adopt, client])

  const login = useCallback(async (tenant: string, email: string, password: string) => {
    const value = await post<Session>('/api/v1/auth/login', { tenant, email, password })
    client.clear()
    adopt(value)
  }, [adopt, client])

  const logout = useCallback(async (message = 'You have signed out.') => {
    try {
      await post('/api/v1/auth/logout')
    } catch {
      // The session may already be gone; local state is cleared either way.
    }
    client.clear()
    adopt(null, message)
  }, [adopt, client])

  const switchTenant = useCallback(async (tenantId: string) => {
    const value = await post<Session>('/api/v1/auth/switch-tenant', { tenant_id: tenantId })
    client.clear()
    adopt(value)
  }, [adopt, client])

  const can = useCallback((...permissions: string[]) => {
    const granted = session?.user.permissions ?? []
    return permissions.length === 0 || permissions.some((permission) => granted.includes(permission))
  }, [session])

  const value = useMemo(() => ({ status, session, notice, login, logout, switchTenant, can }), [status, session, notice, login, logout, switchTenant, can])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
