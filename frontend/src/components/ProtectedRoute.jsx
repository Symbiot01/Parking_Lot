import { Navigate, Outlet } from 'react-router-dom'
import { getUser, isAuthenticated } from '../utils/auth'

export function ProtectedRoute({ role }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  const user = getUser()
  if (role && user?.role !== role) {
    return <Navigate to={user?.role === 'ADMIN' ? '/worker' : '/customer'} replace />
  }
  return <Outlet />
}
