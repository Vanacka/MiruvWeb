<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

interface DayColor {
  date: string
  color: 'green' | 'yellow' | 'red' | 'blue' | 'gray'
  approved_users: string[]
  pending_users: string[]
  is_weekend: boolean
  is_holiday: boolean
  holiday_name: string | null
}
interface VacationRequest {
  id: number
  user_id: number
  date: string
  status: 'pending' | 'approved' | 'rejected'
  created_by_admin: boolean
  request_group_id: number
}
interface UserOption { id: number; full_name: string; role: 'admin' | 'courier' }

const { user } = useAuth()
const isAdmin = computed(() => user.value?.role === 'admin')

const today = new Date()
const year = ref(today.getFullYear())
const month = ref(today.getMonth() + 1)

const monthNames = [
  'Leden', 'Únor', 'Březen', 'Duben', 'Květen', 'Červen',
  'Červenec', 'Srpen', 'Září', 'Říjen', 'Listopad', 'Prosinec',
]
const weekdayNames = ['Po', 'Út', 'St', 'Čt', 'Pá', 'So', 'Ne']

// getDay() vrací 0 = neděle, my chceme posun pro týden začínající pondělím.
const leadingBlanks = computed(() => {
  const firstWeekday = new Date(year.value, month.value - 1, 1).getDay()
  return (firstWeekday + 6) % 7
})

const days = ref<DayColor[]>([])
const pending = ref<VacationRequest[]>([])
const myVacations = ref<VacationRequest[]>([])
const allUsers = ref<UserOption[]>([])
const error = ref('')

async function load() {
  days.value = await api.get<DayColor[]>(`/vacation/calendar?year=${year.value}&month=${month.value}`)
  if (isAdmin.value) {
    pending.value = await api.get<VacationRequest[]>('/vacation/pending')
  } else {
    myVacations.value = await api.get<VacationRequest[]>('/vacation/mine')
  }
}

async function loadUsers() {
  if (!isAdmin.value) return
  allUsers.value = await api.get<UserOption[]>('/auth/users')
}

function courierName(userId: number) {
  return allUsers.value.find((u) => u.id === userId)?.full_name || `#${userId}`
}

// Zamítnutá žádost neblokuje nový pokus o tentýž den (viz backend), takže se
// při hledání "mého" dne bere jen čekající/schválená.
function myVacationFor(dateStr: string): VacationRequest | undefined {
  return myVacations.value.find((v) => v.date === dateStr && v.status !== 'rejected')
}

function changeMonth(delta: number) {
  let m = month.value + delta
  let y = year.value
  if (m > 12) { m = 1; y++ }
  if (m < 1) { m = 12; y-- }
  month.value = m
  year.value = y
  selectedDate.value = null
  load()
}

function dayClasses(d: DayColor) {
  const mine = !isAdmin.value ? myVacationFor(d.date) : undefined
  return {
    'mine-pending': mine?.status === 'pending',
    selected: selectedDate.value === d.date,
  }
}

function dayTitle(d: DayColor): string {
  if (d.is_holiday) return d.holiday_name || 'státní svátek'
  if (d.is_weekend) return 'víkend'
  return [...d.approved_users, ...d.pending_users].join(', ')
}

function dayPeople(d: DayColor): string {
  return [...d.approved_users, ...d.pending_users].join(', ')
}

// Klik na den otevře/zavře detail (hlavně kvůli mobilu, kde není hover) - do
// buňky samotné se tak nemusí vměstnat celý text, když je moc malá.
const selectedDate = ref<string | null>(null)
const selectedDay = computed(() => days.value.find((d) => d.date === selectedDate.value) ?? null)

function selectDay(d: DayColor) {
  selectedDate.value = selectedDate.value === d.date ? null : d.date
}

async function cancelSelected() {
  if (!selectedDay.value) return
  const mine = myVacationFor(selectedDay.value.date)
  if (!mine) return
  error.value = ''
  if (!window.confirm('Opravdu chceš zrušit žádost o dovolenou na tento den?')) return
  try {
    await api.delete(`/vacation/${mine.id}`)
    selectedDate.value = null
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Nepodařilo se zrušit žádost'
  }
}

const rangeStart = ref('')
const rangeEnd = ref('')
const rangeSubmitting = ref(false)

async function submitRange() {
  if (!rangeStart.value || !rangeEnd.value) return
  error.value = ''
  rangeSubmitting.value = true
  try {
    await api.post('/vacation/range', { start_date: rangeStart.value, end_date: rangeEnd.value })
    rangeStart.value = ''
    rangeEnd.value = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Nepodařilo se odeslat žádost'
  } finally {
    rangeSubmitting.value = false
  }
}

interface PendingGroup { group_id: number; user_id: number; dates: string[] }

const pendingGroups = computed<PendingGroup[]>(() => {
  const map = new Map<number, PendingGroup>()
  for (const p of pending.value) {
    let g = map.get(p.request_group_id)
    if (!g) {
      g = { group_id: p.request_group_id, user_id: p.user_id, dates: [] }
      map.set(p.request_group_id, g)
    }
    g.dates.push(p.date)
  }
  return [...map.values()].map((g) => ({ ...g, dates: [...g.dates].sort() }))
})

function periodLabel(g: PendingGroup): string {
  const first = g.dates[0] ?? ''
  const last = g.dates[g.dates.length - 1] ?? ''
  return g.dates.length === 1 ? first : `${first} – ${last} (${g.dates.length} dní)`
}

async function approveGroup(groupId: number) {
  await api.patch(`/vacation/group/${groupId}/approve`)
  await load()
}
async function rejectGroup(groupId: number) {
  await api.patch(`/vacation/group/${groupId}/reject`)
  await load()
}

onMounted(async () => {
  await Promise.all([load(), loadUsers()])
})
</script>

<template>
  <div>
    <h1><span class="eyebrow">Dovolená</span>Kalendář dovolených</h1>

    <div class="card">
      <div class="calendar-wrap">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
          <button class="btn secondary" @click="changeMonth(-1)">&larr;</button>
          <strong>{{ monthNames[month - 1] }} {{ year }}</strong>
          <button class="btn secondary" @click="changeMonth(1)">&rarr;</button>
        </div>
        <div class="calendar-grid">
          <div v-for="w in weekdayNames" :key="w" class="cal-day-header">{{ w }}</div>
          <div v-for="n in leadingBlanks" :key="`blank-${n}`"></div>
          <div
            v-for="d in days"
            :key="d.date"
            class="cal-day"
            :class="[d.color, dayClasses(d)]"
            :title="dayTitle(d)"
            @click="selectDay(d)"
          >
            <span>{{ d.date.slice(-2) }}</span>
            <span v-if="d.holiday_name" class="cal-day-sublabel">{{ d.holiday_name }}</span>
            <span
              v-else-if="d.approved_users.length || d.pending_users.length"
              class="cal-day-sublabel"
            >
              {{ dayPeople(d) }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="selectedDay" style="border:1px solid var(--border);border-radius:8px;padding:12px;margin-top:14px">
        <p style="margin:0 0 6px;font-weight:600">{{ selectedDay.date }}</p>
        <p v-if="selectedDay.holiday_name" style="margin:0 0 4px;font-size:13px">Státní svátek: {{ selectedDay.holiday_name }}</p>
        <p v-else-if="selectedDay.is_weekend" style="margin:0 0 4px;font-size:13px">Víkend</p>
        <p v-if="selectedDay.approved_users.length" style="margin:0 0 4px;font-size:13px">
          Schválená dovolená: {{ selectedDay.approved_users.join(', ') }}
        </p>
        <p v-if="selectedDay.pending_users.length" style="margin:0 0 4px;font-size:13px">
          Čeká na schválení: {{ selectedDay.pending_users.join(', ') }}
        </p>
        <p
          v-if="!selectedDay.holiday_name && !selectedDay.is_weekend && !selectedDay.approved_users.length && !selectedDay.pending_users.length"
          style="margin:0;font-size:13px;color:var(--muted)"
        >
          Volno.
        </p>
        <button
          v-if="!isAdmin && myVacationFor(selectedDay.date)"
          class="btn secondary"
          style="margin-top:8px"
          @click="cancelSelected"
        >
          Zrušit žádost
        </button>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <p style="font-size:12px;color:var(--muted);margin-top:14px">
        🟢 volno &nbsp; 🟡 čeká na schválení &nbsp; 🔴 obsazeno &nbsp; 🔵 tvoje schválená dovolená &nbsp;
        ⚪ víkend/svátek
      </p>
    </div>

    <div class="card" v-if="!isAdmin">
      <h3 style="margin-top:0">Požádat o dovolenou</h3>
      <div class="form-row">
        <div class="field">
          <label>Od</label>
          <input v-model="rangeStart" type="date" />
        </div>
        <div class="field">
          <label>Do</label>
          <input v-model="rangeEnd" type="date" />
        </div>
      </div>
      <button class="btn" :disabled="rangeSubmitting || !rangeStart || !rangeEnd" @click="submitRange">
        {{ rangeSubmitting ? 'Odesílám…' : 'Odeslat žádost' }}
      </button>
    </div>

    <div class="card" v-if="isAdmin">
      <h3 style="margin-top:0">Čeká na schválení</h3>
      <table v-if="pendingGroups.length">
        <thead><tr><th>Období</th><th>Kurýr</th><th></th></tr></thead>
        <tbody>
          <tr v-for="g in pendingGroups" :key="g.group_id">
            <td>{{ periodLabel(g) }}</td>
            <td>{{ courierName(g.user_id) }}</td>
            <td>
              <button class="btn" style="margin-right:6px" @click="approveGroup(g.group_id)">Schválit</button>
              <button class="btn secondary" @click="rejectGroup(g.group_id)">Zamítnout</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else style="color:var(--muted)">Nic nečeká na schválení.</p>
    </div>
  </div>
</template>
