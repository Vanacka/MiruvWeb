<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

interface DayColor {
  date: string
  color: 'green' | 'yellow' | 'red'
  approved_users: string[]
  pending_users: string[]
}
interface VacationRequest {
  id: number
  user_id: number
  date: string
  status: 'pending' | 'approved' | 'rejected'
  created_by_admin: boolean
}

const { user } = useAuth()
const isAdmin = computed(() => user.value?.role === 'admin')

const today = new Date()
const year = ref(today.getFullYear())
const month = ref(today.getMonth() + 1)

const days = ref<DayColor[]>([])
const pending = ref<VacationRequest[]>([])
const error = ref('')

async function load() {
  days.value = await api.get<DayColor[]>(`/vacation/calendar?year=${year.value}&month=${month.value}`)
  if (isAdmin.value) {
    pending.value = await api.get<VacationRequest[]>('/vacation/pending')
  }
}

function changeMonth(delta: number) {
  let m = month.value + delta
  let y = year.value
  if (m > 12) { m = 1; y++ }
  if (m < 1) { m = 12; y-- }
  month.value = m
  year.value = y
  load()
}

async function requestDay(d: DayColor) {
  if (isAdmin.value) return
  error.value = ''
  try {
    await api.post('/vacation', { date: d.date })
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Nepodařilo se odeslat žádost'
  }
}

async function approve(id: number) {
  await api.patch(`/vacation/${id}/approve`)
  await load()
}
async function reject(id: number) {
  await api.patch(`/vacation/${id}/reject`)
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <h1><span class="eyebrow">Dovolená</span>Kalendář dovolených</h1>

    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
        <button class="btn secondary" @click="changeMonth(-1)">&larr;</button>
        <strong>{{ month }}/{{ year }}</strong>
        <button class="btn secondary" @click="changeMonth(1)">&rarr;</button>
      </div>
      <div class="calendar-grid">
        <div
          v-for="d in days"
          :key="d.date"
          class="cal-day"
          :class="d.color"
          :title="[...d.approved_users, ...d.pending_users].join(', ')"
          @click="requestDay(d)"
        >
          {{ d.date.slice(-2) }}
        </div>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <p style="font-size:12px;color:var(--muted);margin-top:14px">
        🟢 volno &nbsp; 🟡 čeká na schválení &nbsp; 🔴 nejde vzít dovolenou
      </p>
    </div>

    <div class="card" v-if="isAdmin">
      <h3 style="margin-top:0">Čeká na schválení</h3>
      <table v-if="pending.length">
        <thead><tr><th>Datum</th><th>Kurýr ID</th><th></th></tr></thead>
        <tbody>
          <tr v-for="p in pending" :key="p.id">
            <td>{{ p.date }}</td>
            <td>{{ p.user_id }}</td>
            <td>
              <button class="btn" style="margin-right:6px" @click="approve(p.id)">Schválit</button>
              <button class="btn secondary" @click="reject(p.id)">Zamítnout</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else style="color:var(--muted)">Nic nečeká na schválení.</p>
    </div>
  </div>
</template>
