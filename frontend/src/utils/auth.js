const USER_KEY = 'user'
const TOKEN_KEY = 'access_token'

export function saveAuth(data) {
  localStorage.setItem(TOKEN_KEY, data.access_token)
  localStorage.setItem(
    USER_KEY,
    JSON.stringify({
      id: data.user_id,
      name: data.name,
      email: data.email,
      role: data.role,
    }),
  )
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getUser() {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function isAuthenticated() {
  return Boolean(getToken() && getUser())
}
