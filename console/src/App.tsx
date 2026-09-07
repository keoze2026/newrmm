import { Navigate, Route, Routes } from 'react-router-dom'
import Shell from './components/Shell'
import AuditPage from './pages/AuditPage'
import DevicesPage from './pages/DevicesPage'
import LoginPage from './pages/LoginPage'
import SessionsPage from './pages/SessionsPage'
import { useAuth } from './lib/auth'

export default function App() {
  const { operator, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-400">
        Loading console…
      </div>
    )
  }

  if (!operator) return <LoginPage />

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Navigate to="/sessions" replace />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/devices" element={<DevicesPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="*" element={<Navigate to="/sessions" replace />} />
      </Routes>
    </Shell>
  )
}
