<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

interface Route { id: number; name: string }
interface Entry {
  id: number
  user_id: number
  route_id: number
  date: string
  km_driven: number
  packages_delivered: number
  hours_worked: number
  note: string | null
  confirmed: boolean
}
interface Average {
  user_id: number
  full_name: string
  avg_km: number
  avg_packages: number
  avg_hours: number
  entries_count: number
}

const { user } = useAuth()
const isAdmin = computed(() => user.value?.role === 'admin')

const routes = ref<Route[]>([])
const myRoutes = ref<Route[]>([])
const entries = ref<Entry[]>([])
const averages = ref<Average[]>([])

const selectedRoute = ref<number | null>(null)
const filterMonth = ref(new Date().getMonth() + 1)
const filterYear = ref(new Date().getFullYear())

const form = ref({
  route_id: null as number | null,
  date: new Date().toISOString().slice(0, 10),
  km_driven: 0,
  packages_delivered: 0,
  hours_worked: 0,
  note: '',
  confirmed: false,
})
const submitting = ref(false)
const formError = ref('')

async function loadRoutes() {
  routes.value = await api.get<Route[]>('/performance/routes')
  myRoutes.value = await api.get<Route[]>('/performance/routes/mine')
}

async function loadEntries() {
  const params = new URLSearchParams()
  if (selectedRoute.value) params.set('route_id', String(selectedRoute.value))
  params.set('year', String(filterYear.value))
  params.set('month', String(filterMonth.value))
  entries.value = await api.get<Entry[]>(`/performance?${params}`)
}

async function loadAverages() {
  if (!isAdmin.value) return
  averages.value = await api.get<Average[]>(
    `/performance/averages?year=${filterYear.value}&month=${filterMonth.value}`
  )
}

async function submit() {
  formError.value = ''
  if (!form.value.route_id) {
    formError.value = 'Vyber trasu'
    return
  }
  submitting.value = true
  try {
    await api.post('/performance', form.value)
    form.value.note = ''
    form.value.confirmed = false
    await loadEntries()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : 'Nepodařilo se uložit'
  } finally {
    submitting.value = false
  }
}

function exportCsv() {
  const token = localStorage.getItem('token')
  const url = `${api.API_URL}/performance/export.csv?year=${filterYear.value}&month=${filterMonth.value}`
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then((r) => r.blob())
    .then((blob) => {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'vykon.csv'
      a.click()
    })
}

onMounted(async () => {
  await loadRoutes()
  await loadEntries()
  await loadAverages()
})
</script>

<template>
  <div>
    <h1><span class="eyebrow">Denní výkon</span>Formulář na denní výkon</h1>

    <div class="card">
      <h3 style="margin-top:0">Nový záznam</h3>
      <form @submit.prevent="submit">
        <div class="form-row">
          <div class="field">
            <label>Trasa</label>
            <select v-model.number="form.route_id" required>
              <option :value="null" disabled>Vyber trasu</option>
              <option v-for="r in myRoutes" :key="r.id" :value="r.id">{{ r.name }}</option>
            </select>
            <p v-if="!myRoutes.length" style="font-size: 12px; color: var(--muted); margin: 4px 0 0">
              Zatím nejsou založené žádné trasy.
            </p>
          </div>
          <div class="field">
            <label>Datum</label>
            <input v-model="form.date" type="date" required />
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label>Kilometry</label>
            <input v-model.number="form.km_driven" type="number" step="0.1" />
          </div>
          <div class="field">
            <label>Počet zásilek</label>
            <input v-model.number="form.packages_delivered" type="number" />
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label>Odpracované hodiny</label>
            <input v-model.number="form.hours_worked" type="number" step="0.1" />
          </div>
          <div class="field">
            <label>Poznámka</label>
            <input v-model="form.note" />
          </div>
        </div>
        <div class="field" style="display:flex;align-items:center;gap:8px">
          <input id="confirmed" type="checkbox" v-model="form.confirmed" style="width:auto" />
          <label for="confirmed" style="margin:0">Formulář je kompletně vyplněný</label>
        </div>
        <p style="font-size:12px;color:var(--muted);margin-top:-8px">
          Pokud checkbox neodškrtneš, Mirkovi přijde upozornění.
        </p>
        <button class="btn" type="submit" :disabled="submitting">
          {{ submitting ? 'Ukládám…' : 'Uložit záznam' }}
        </button>
        <p v-if="formError" class="error">{{ formError }}</p>
      </form>
    </div>

    <div class="card">
      <div style="display:flex;gap:12px;align-items:end;margin-bottom:14px;flex-wrap:wrap">
        <div class="field" style="margin:0">
          <label>Trasa</label>
          <select v-model.number="selectedRoute" @change="loadEntries">
            <option :value="null">Všechny</option>
            <option v-for="r in routes" :key="r.id" :value="r.id">{{ r.name }}</option>
          </select>
        </div>
        <div class="field" style="margin:0">
          <label>Měsíc</label>
          <input v-model.number="filterMonth" type="number" min="1" max="12" @change="loadEntries(); loadAverages()" style="width:80px" />
        </div>
        <div class="field" style="margin:0">
          <label>Rok</label>
          <input v-model.number="filterYear" type="number" @change="loadEntries(); loadAverages()" style="width:100px" />
        </div>
        <button v-if="isAdmin" class="btn secondary" @click="exportCsv">Export do CSV</button>
      </div>

      <table>
        <thead>
          <tr>
            <th>Datum</th><th>Trasa</th><th class="num">Km</th><th class="num">Zásilky</th>
            <th class="num">Hodiny</th><th>Potvrzeno</th><th>Poznámka</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in entries" :key="e.id">
            <td>{{ e.date }}</td>
            <td>{{ routes.find(r => r.id === e.route_id)?.name || e.route_id }}</td>
            <td class="num">{{ e.km_driven }}</td>
            <td class="num">{{ e.packages_delivered }}</td>
            <td class="num">{{ e.hours_worked }}</td>
            <td>{{ e.confirmed ? '✓' : '—' }}</td>
            <td>{{ e.note }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card" v-if="isAdmin && averages.length">
      <h3 style="margin-top:0">Měsíční průměry</h3>
      <table>
        <thead>
          <tr><th>Kurýr</th><th class="num">Prům. km</th><th class="num">Prům. zásilky</th><th class="num">Prům. hodiny</th><th class="num">Záznamů</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in averages" :key="a.user_id">
            <td>{{ a.full_name }}</td>
            <td class="num">{{ a.avg_km.toFixed(1) }}</td>
            <td class="num">{{ a.avg_packages.toFixed(1) }}</td>
            <td class="num">{{ a.avg_hours.toFixed(1) }}</td>
            <td class="num">{{ a.entries_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
