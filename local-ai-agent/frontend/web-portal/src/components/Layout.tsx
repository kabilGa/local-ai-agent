import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import LocalModelBadge from './chat/LocalModelBadge'

const navItems = [
  { to: '/chat', label: 'Chat' },
  { to: '/history', label: 'History' },
  { to: '/reports', label: 'Reports' },
  { to: '/admin', label: 'Admin', roles: ['admin', 'auditor'] as const },
]

export default function Layout() {
  const { user, logout } = useAuth()

  const visibleNav = navItems.filter(
    (item) =>
      !item.roles || (user && item.roles.includes(user.role as 'admin' | 'auditor')),
  )

  return (
    <div className="flex min-h-screen bg-[#0a0a0f] text-slate-100">
      <aside className="flex w-56 shrink-0 flex-col border-r border-[#1e1e2e] bg-[#111118]">
        <div className="border-b border-[#1e1e2e] px-4 py-5">
          <h1 className="text-lg font-semibold">AI Agent</h1>
          <p className="mt-1 text-xs text-slate-500">Local · Open source</p>
        </div>

        <nav className="flex flex-1 flex-col gap-1 p-3">
          {visibleNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'bg-[#7c3aed]/20 text-violet-300'
                    : 'text-slate-400 hover:bg-[#1e1e2e] hover:text-slate-200'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-[#1e1e2e] p-4">
          <p className="truncate text-sm text-slate-300">{user?.name}</p>
          <p className="truncate text-xs text-slate-500">{user?.role}</p>
          <button
            type="button"
            onClick={logout}
            className="mt-3 w-full rounded-lg border border-[#1e1e2e] px-3 py-1.5 text-xs text-slate-400 hover:bg-[#1e1e2e]"
          >
            Log out
          </button>
        </div>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center border-b border-[#1e1e2e] bg-[#111118] px-4 py-2">
          <LocalModelBadge />
        </div>
        <main className="flex flex-1 flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
