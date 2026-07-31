<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api/client'

interface Route {
  id: number
  name: string
}
interface User {
  id: number
  username: string
  full_name: string
  role: 'admin' | 'courier'
  vacation_days_limit: number
  is_active: boolean
  preferred_routes: Route[]
}

const users = ref<User[]>([])
const routes = ref<Route[]>([])
const expandedUser = ref<number | null>(null)
const savingUserId = ref<number | null>(null)
const togglingActiveId = ref<number | null>(null)
const deletingRouteId = ref<number | null>(null)
const routeDeleteError = ref('')

const form = ref({
  username: '',
  password: '',
  full_name: '',
  role: 'courier' as 'admin' | 'courier',
  vacation_days_limit: 20,
})
const newUserRouteIds = ref<number[]>([])
const submitting = ref(false)
const error = ref('')
const success = ref('')

const routeName = ref('')
const routeSubmitting = ref(false)
const routeError = ref('')

async function load() {
  users.value = await api.get<User[]>('/auth/users')
  routes.value = await api.get<Route[]>('/performance/routes')
}

function toggleNewUserRoute(routeId: number) {
  const idx = newUserRouteIds.value.indexOf(routeId)
  if (idx === -1) newUserRouteIds.value.push(routeId)
  else newUserRouteIds.value.splice(idx, 1)
}

async function submit() {
  error.value = ''
  success.value = ''
  submitting.value = true
  try {
    const created = await api.post<User>('/auth/users', form.value)
    if (form.value.role === 'courier' && newUserRouteIds.value.length) {
      await api.put(`/performance/routes/assignments/${created.id}`, { route_ids: newUserRouteIds.value })
    }
    success.value = `Účet pro ${form.value.full_name} byl vytvořen.`
    form.value = { username: '', password: '', full_name: '', role: 'courier', vacation_days_limit: 20 }
    newUserRouteIds.value = []
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Nepodařilo se založit účet'
  } finally {
    submitting.value = false
  }
}

async function submitRoute() {
  routeError.value = ''
  if (!routeName.value.trim()) return
  routeSubmitting.value = true
  try {
    await api.post('/performance/routes', { name: routeName.value.trim() })
    routeName.value = ''
    await load()
  } catch (e) {
    routeError.value = e instanceof Error ? e.message : 'Nepodařilo se založit trasu'
  } finally {
    routeSubmitting.value = false
  }
}

async function deleteRoute(r: Route) {
  routeDeleteError.value = ''
  if (!window.confirm(`Opravdu smazat trasu "${r.name}"? Jde jen dokud na ni nikdy nikdo nevyplnil formulář.`)) return
  deletingRouteId.value = r.id
  try {
    await api.delete(`/performance/routes/${r.id}`)
    await load()
  } catch (e) {
    routeDeleteError.value = e instanceof Error ? e.message : 'Nepodařilo se smazat trasu'
  } finally {
    deletingRouteId.value = null
  }
}

async function toggleUserActive(u: User) {
  const goingInactive = u.is_active
  const message = goingInactive
    ? `Opravdu deaktivovat ${u.full_name}? Přihlášení přestane fungovat, ale historie (nafta, dovolená, výkon) zůstane zachovaná - jde to kdykoliv vrátit zpět.`
    : `Znovu aktivovat ${u.full_name}?`
  if (!window.confirm(message)) return
  togglingActiveId.value = u.id
  try {
    const updated = await api.patch<User>(`/auth/users/${u.id}/active`, { is_active: !u.is_active })
    u.is_active = updated.is_active
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Nepodařilo se změnit stav účtu'
  } finally {
    togglingActiveId.value = null
  }
}

function toggleExpand(user: User) {
  if (user.role !== 'courier') return
  expandedUser.value = expandedUser.value === user.id ? null : user.id
}

function hasRoute(user: User, routeId: number) {
  return user.preferred_routes.some((r) => r.id === routeId)
}

async function toggleRoute(user: User, routeId: number) {
  if (savingUserId.value) return
  const current = new Set(user.preferred_routes.map((r) => r.id))
  if (current.has(routeId)) current.delete(routeId)
  else current.add(routeId)

  savingUserId.value = user.id
  try {
    user.preferred_routes = await api.put<Route[]>(`/performance/routes/assignments/${user.id}`, {
      route_ids: [...current],
    })
  } finally {
    savingUserId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1><span class="eyebrow">Správa</span>Zaměstnanci</h1>

    <div class="card">
      <h3 style="margin-top:0">Nový zaměstnanec</h3>
      <form @submit.prevent="submit">
        <div class="form-row">
          <div class="field">
            <label>Celé jméno</label>
            <input v-model="form.full_name" required />
          </div>
          <div class="field">
            <label>Uživatelské jméno pro přihlášení</label>
            <input v-model="form.username" required autocomplete="off" />
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label>Heslo</label>
            <input v-model="form.password" type="password" required autocomplete="new-password" />
          </div>
          <div class="field">
            <label>Limit dní dovolené / rok</label>
            <input v-model.number="form.vacation_days_limit" type="number" />
          </div>
        </div>
        <div class="field">
          <label>Role</label>
          <select v-model="form.role">
            <option value="courier">Kurýr</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div class="field" v-if="form.role === 'courier'">
          <label>Preferované trasy</label>
          <p v-if="!routes.length" style="font-size:13px;color:var(--muted);margin:0">
            Zatím nejsou založené žádné trasy - založ je níže. Bez výběru smí kurýr zatím na všechny.
          </p>
          <div v-else style="display:flex;flex-wrap:wrap;gap:12px">
            <label
              v-for="r in routes"
              :key="r.id"
              style="display:flex;align-items:center;gap:6px;font-weight:400;font-size:14px;width:auto;margin:0"
            >
              <input
                type="checkbox"
                style="width:auto"
                :checked="newUserRouteIds.includes(r.id)"
                @change="toggleNewUserRoute(r.id)"
              />
              {{ r.name }}
            </label>
          </div>
        </div>
        <button class="btn" type="submit" :disabled="submitting">
          {{ submitting ? 'Zakládám…' : 'Založit účet' }}
        </button>
        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="success" style="color: var(--green); font-size: 13px; margin-top: 8px">{{ success }}</p>
      </form>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Trasy</h3>
      <form @submit.prevent="submitRoute" style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:14px">
        <div class="field" style="margin:0;flex:1;min-width:160px">
          <label>Název nové trasy</label>
          <input v-model="routeName" placeholder="např. Praha - jih" />
        </div>
        <button class="btn secondary" type="submit" :disabled="routeSubmitting">
          {{ routeSubmitting ? 'Zakládám…' : 'Přidat trasu' }}
        </button>
      </form>
      <p v-if="routeError" class="error" style="margin-top:-8px">{{ routeError }}</p>
      <p v-if="routeDeleteError" class="error" style="margin-top:-8px">{{ routeDeleteError }}</p>
      <p v-if="!routes.length" style="color:var(--muted);margin:0">Zatím nejsou založené žádné trasy.</p>
      <div v-else style="display:flex;flex-wrap:wrap;gap:8px">
        <span v-for="r in routes" :key="r.id" style="display:inline-flex;align-items:center;gap:6px">
          <span class="badge paid">{{ r.name }}</span>
          <button
            type="button"
            class="btn secondary"
            style="padding:2px 8px;font-size:12px;color:var(--red)"
            :disabled="deletingRouteId === r.id"
            @click="deleteRoute(r)"
          >
            {{ deletingRouteId === r.id ? 'Mažu…' : 'Smazat' }}
          </button>
        </span>
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Přehled účtů</h3>
      <p style="font-size:12px;color:var(--muted);margin-top:-8px">
        Klikni na kurýra a přiřaď mu trasy, na které smí vyplňovat formulář výkonu. Bez přiřazení smí zatím na všechny.
      </p>
      <table>
        <thead>
          <tr><th>Jméno</th><th>Login</th><th>Role</th><th class="num">Limit dovolené</th><th>Stav</th><th></th></tr>
        </thead>
        <tbody>
          <template v-for="u in users" :key="u.id">
            <tr
              @click="toggleExpand(u)"
              :style="u.role === 'courier' ? 'cursor:pointer' : ''"
            >
              <td>{{ u.full_name }}</td>
              <td>{{ u.username }}</td>
              <td>{{ u.role === 'admin' ? 'admin' : 'kurýr' }}</td>
              <td class="num">{{ u.vacation_days_limit }}</td>
              <td>
                <span class="badge" :class="u.is_active ? 'paid' : 'unpaid'">
                  {{ u.is_active ? 'aktivní' : 'neaktivní' }}
                </span>
              </td>
              <td>
                <button
                  type="button"
                  class="btn secondary"
                  :style="u.is_active ? 'color:var(--red)' : ''"
                  :disabled="togglingActiveId === u.id"
                  @click.stop="toggleUserActive(u)"
                >
                  {{ togglingActiveId === u.id ? 'Ukládám…' : u.is_active ? 'Deaktivovat' : 'Aktivovat' }}
                </button>
              </td>
            </tr>
            <tr v-if="u.role === 'courier' && expandedUser === u.id">
              <td colspan="6" style="background:var(--paper)">
                <div style="font-size:12px;color:var(--muted);margin-bottom:8px">
                  Preferované trasy pro {{ u.full_name }}
                </div>
                <div v-if="!routes.length" style="font-size:13px;color:var(--muted)">
                  Nejdřív založ aspoň jednu trasu výše.
                </div>
                <div v-else style="display:flex;flex-wrap:wrap;gap:12px">
                  <label
                    v-for="r in routes"
                    :key="r.id"
                    style="display:flex;align-items:center;gap:6px;font-weight:400;font-size:13px;width:auto;margin:0;color:var(--ink)"
                  >
                    <input
                      type="checkbox"
                      style="width:auto"
                      :checked="hasRoute(u, r.id)"
                      :disabled="savingUserId === u.id"
                      @click.stop="toggleRoute(u, r.id)"
                    />
                    {{ r.name }}
                  </label>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
