import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
    { path: '/nafta', name: 'fuel', component: () => import('../views/FuelView.vue') },
    { path: '/dovolena', name: 'vacation', component: () => import('../views/VacationView.vue') },
    { path: '/vykon', name: 'performance', component: () => import('../views/PerformanceView.vue') },
    {
      path: '/zamestnanci',
      name: 'users',
      component: () => import('../views/UsersView.vue'),
      meta: { adminOnly: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const isAuthed = !!localStorage.getItem('token')
  if (to.name !== 'login' && !isAuthed) return { name: 'login' }
  if (to.name === 'login' && isAuthed) return { name: 'home' }

  if (to.meta.adminOnly) {
    const { user, fetchMe } = useAuth()
    if (!user.value) await fetchMe()
    if (user.value?.role !== 'admin') return { name: 'home' }
  }
})

export default router
