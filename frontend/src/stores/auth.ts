import { ref } from 'vue'
import { api } from '../api/client'

export interface CurrentUser {
  id: number
  username: string
  full_name: string
  role: 'admin' | 'courier'
  vacation_days_limit: number
}

const user = ref<CurrentUser | null>(null)
const loading = ref(false)

async function fetchMe() {
  if (!localStorage.getItem('token')) return
  loading.value = true
  try {
    user.value = await api.get<CurrentUser>('/auth/me')
  } catch {
    user.value = null
  } finally {
    loading.value = false
  }
}

function logout() {
  localStorage.removeItem('token')
  user.value = null
  window.location.href = '/login'
}

export function useAuth() {
  return { user, loading, fetchMe, logout }
}
