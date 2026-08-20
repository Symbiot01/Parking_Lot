import { Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './components/ProtectedRoute'
import Login from './pages/Login'
import Register from './pages/Register'
import CustomerDashboard from './pages/customer/CustomerDashboard'
import WorkerDashboard from './pages/worker/WorkerDashboard'
import { getUser, isAuthenticated } from './utils/auth'

function HomeRedirect() {
  if (!isAuthenticated()) return <Navigate to="/login" replace />
  const user = getUser()
  return <Navigate to={user?.role === 'ADMIN' ? '/worker' : '/customer'} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomeRedirect />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route element={<ProtectedRoute role="ADMIN" />}>
        <Route path="/worker" element={<WorkerDashboard />} />
      </Route>

      <Route element={<ProtectedRoute role="PUBLIC" />}>
        <Route path="/customer" element={<CustomerDashboard />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
