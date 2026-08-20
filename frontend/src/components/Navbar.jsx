import { Link, useNavigate } from 'react-router-dom'
import { clearAuth, getUser } from '../utils/auth'

export default function Navbar({ title }) {
  const navigate = useNavigate()
  const user = getUser()

  function logout() {
    clearAuth()
    navigate('/login')
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div>
          <Link to={user?.role === 'ADMIN' ? '/worker' : '/customer'} className="text-lg font-semibold text-brand-700">
            Parking Lot
          </Link>
          {title ? <p className="text-sm text-slate-500">{title}</p> : null}
        </div>
        <div className="flex items-center gap-4">
          <span className="hidden text-sm text-slate-600 sm:inline">
            {user?.name} · <span className="font-medium">{user?.role}</span>
          </span>
          <button
            type="button"
            onClick={logout}
            className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-200"
          >
            Logout
          </button>
        </div>
      </div>
    </header>
  )
}
