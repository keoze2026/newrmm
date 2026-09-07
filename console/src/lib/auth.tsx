import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, loadToken, setToken, type Operator } from './api'

interface AuthState {
  operator: Operator | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [operator, setOperator] = useState<Operator | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Restore the session on reload if the token is still in sessionStorage.
    const token = loadToken()
    if (!token) {
      setLoading(false)
      return
    }
    api
      .me()
      .then(setOperator)
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(email: string, password: string) {
    const { access_token } = await api.login(email, password)
    setToken(access_token)
    setOperator(await api.me())
  }

  function logout() {
    setToken(null)
    setOperator(null)
  }

  return (
    <AuthContext.Provider value={{ operator, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
