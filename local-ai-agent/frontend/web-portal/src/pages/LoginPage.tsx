import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function LoginPage() {
  const { login, isAuthenticated, isLoading } = useAuth()
  const [email, setEmail] = useState('dev@local.agent')
  const [password, setPassword] = useState('password')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (isAuthenticated) {
    return <Navigate to="/chat" replace />
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-8"
      >
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Sign in</h1>
          <p className="mt-2 text-sm text-slate-400">
            Local AI Agent — mock auth (use any password)
          </p>
        </div>

        <label className="block text-sm text-slate-400">
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-slate-100 outline-none focus:border-violet-500"
          />
        </label>

        <label className="block text-sm text-slate-400">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-slate-100 outline-none focus:border-violet-500"
          />
        </label>

        <p className="text-xs text-slate-500">
          Try <code className="text-violet-300">admin@local.agent</code> for admin
          access, or <code className="text-violet-300">auditor@local.agent</code> for
          auditor role.
        </p>

        {error && <p className="text-sm text-red-300">{error}</p>}

        <button
          type="submit"
          disabled={busy || isLoading}
          className="w-full rounded-xl bg-violet-600 py-3 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
