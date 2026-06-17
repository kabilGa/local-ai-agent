import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { getAdminSettings, getAdminUsers } from '../api/admin'
import { useAuth } from '../auth/AuthContext'
import type { AdminSettings, AdminUser } from '../types'

export default function AdminPage() {
  const { user } = useAuth()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (user?.role !== 'admin' && user?.role !== 'auditor') return

    Promise.all([getAdminUsers(), getAdminSettings()])
      .then(([u, s]) => {
        setUsers(u)
        setSettings(s)
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : 'Failed to load admin data'),
      )
      .finally(() => setLoading(false))
  }, [user?.role])

  if (user?.role !== 'admin' && user?.role !== 'auditor') {
    return <Navigate to="/chat" replace />
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-slate-800 px-6 py-4">
        <h2 className="text-lg font-semibold">Administration</h2>
        <p className="mt-1 text-sm text-slate-400">
          Users, quotas, and platform settings
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {loading && <p className="text-slate-500">Loading…</p>}
        {error && <p className="text-red-300">{error}</p>}

        {settings && (
          <section className="mb-8 rounded-xl border border-slate-800 bg-slate-900/50 p-5">
            <h3 className="font-medium text-slate-100">Platform settings</h3>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-slate-500">Max tokens / day</dt>
                <dd className="text-slate-200">
                  {settings.maxTokensPerDay.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Max requests / hour</dt>
                <dd className="text-slate-200">{settings.maxRequestsPerHour}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Offline mode</dt>
                <dd className="text-slate-200">
                  {settings.offlineMode ? 'Enabled' : 'Disabled'}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Default explain mode</dt>
                <dd className="capitalize text-slate-200">
                  {settings.defaultExplainMode}
                </dd>
              </div>
            </dl>
          </section>
        )}

        <section>
          <h3 className="font-medium text-slate-100">Users</h3>
          <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-900/80 text-slate-400">
                <tr>
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Role</th>
                  <th className="px-4 py-3 font-medium">Last login</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-slate-800/50">
                    <td className="px-4 py-3 text-slate-200">{u.name}</td>
                    <td className="px-4 py-3 text-slate-400">{u.email}</td>
                    <td className="px-4 py-3 capitalize text-violet-300">{u.role}</td>
                    <td className="px-4 py-3 text-slate-500">
                      {new Date(u.lastLogin).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
}
