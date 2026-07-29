<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

interface Route { id: number; name: string }
interface FieldDef {
  id: number
  key: string
  label: string
  field_type: 'number' | 'text'
  required: boolean
  position: number
  active: boolean
}
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
  extra_fields: Record<string, string | number>
  is_weekend: boolean
  is_holiday: boolean
  edit_count: number
  is_late_edit: boolean
}
interface Average {
  user_id: number
  full_name: string
  avg_km: number
  avg_packages: number
  avg_hours: number
  entries_count: number
}
interface UserOption { id: number; full_name: string; role: 'admin' | 'courier' }
interface EditLogEntry {
  id: number
  edited_by_id: number
  edited_by_name: string
  edited_at: string
  changes: Record<string, { old: unknown; new: unknown }>
}

const fieldLabels: Record<string, string> = {
  route_id: 'Trasa',
  date: 'Datum',
  km_driven: 'Kilometry',
  packages_delivered: 'Počet zásilek',
  hours_worked: 'Odpracované hodiny',
  note: 'Poznámka',
  confirmed: 'Potvrzeno',
  extra_fields: 'Vlastní pole',
}

const { user } = useAuth()
const isAdmin = computed(() => user.value?.role === 'admin')

const routes = ref<Route[]>([])
const myRoutes = ref<Route[]>([])
const activeFields = ref<FieldDef[]>([])
const allFields = ref<FieldDef[]>([])
const entries = ref<Entry[]>([])
const averages = ref<Average[]>([])
const allUsers = ref<UserOption[]>([])

const selectedRoute = ref<number | null>(null)
const selectedCourier = ref<number | null>(null)
const filterMode = ref<'month' | 'day'>('month')
const filterMonth = ref(new Date().getMonth() + 1)
const filterYear = ref(new Date().getFullYear())
const filterDay = ref(new Date().toISOString().slice(0, 10))

watch(filterDay, (val) => {
  const [y, m] = val.split('-').map(Number)
  if (y) filterYear.value = y
  if (m) filterMonth.value = m
})

function emptyForm() {
  return {
    route_id: null as number | null,
    date: new Date().toISOString().slice(0, 10),
    km_driven: 0,
    packages_delivered: 0,
    hours_worked: 0,
    note: '',
    confirmed: false,
    extra_fields: {} as Record<string, string>,
  }
}

const form = ref(emptyForm())
const submitting = ref(false)
const formError = ref('')
const editingId = ref<number | null>(null)

const newField = ref({ label: '', field_type: 'number' as 'number' | 'text', required: false })
const fieldSubmitting = ref(false)
const fieldError = ref('')

const expandedLogId = ref<number | null>(null)
const editLogs = ref<Record<number, EditLogEntry[]>>({})
const loadingLog = ref<number | null>(null)

function courierName(userId: number) {
  return allUsers.value.find((u) => u.id === userId)?.full_name || `#${userId}`
}

function canEdit(e: Entry) {
  return isAdmin.value || e.user_id === user.value?.id
}

function formatChangeValue(field: string, value: unknown) {
  if (field === 'route_id') return routes.value.find((r) => r.id === value)?.name ?? value
  if (field === 'confirmed') return value ? 'ano' : 'ne'
  if (field === 'extra_fields') return JSON.stringify(value)
  return value
}

async function loadRoutes() {
  routes.value = await api.get<Route[]>('/performance/routes')
  myRoutes.value = await api.get<Route[]>('/performance/routes/mine')
}

async function loadFields() {
  activeFields.value = await api.get<FieldDef[]>('/performance/fields/active')
  if (isAdmin.value) {
    allFields.value = await api.get<FieldDef[]>('/performance/fields')
  }
}

async function loadUsers() {
  if (!isAdmin.value) return
  allUsers.value = await api.get<UserOption[]>('/auth/users')
}

async function loadEntries() {
  const params = new URLSearchParams()
  if (selectedRoute.value) params.set('route_id', String(selectedRoute.value))
  if (isAdmin.value && selectedCourier.value) params.set('user_id', String(selectedCourier.value))
  if (filterMode.value === 'day') {
    const [y, m, d] = filterDay.value.split('-').map(Number)
    params.set('year', String(y))
    params.set('month', String(m))
    params.set('day', String(d))
  } else {
    params.set('year', String(filterYear.value))
    params.set('month', String(filterMonth.value))
  }
  entries.value = await api.get<Entry[]>(`/performance?${params}`)
}

async function loadAverages() {
  if (!isAdmin.value) return
  averages.value = await api.get<Average[]>(
    `/performance/averages?year=${filterYear.value}&month=${filterMonth.value}`,
  )
}

function refreshFiltered() {
  loadEntries()
  loadAverages()
}

function startEdit(e: Entry) {
  editingId.value = e.id
  form.value = {
    route_id: e.route_id,
    date: e.date,
    km_driven: e.km_driven,
    packages_delivered: e.packages_delivered,
    hours_worked: e.hours_worked,
    note: e.note || '',
    confirmed: e.confirmed,
    extra_fields: { ...e.extra_fields } as Record<string, string>,
  }
  formError.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function cancelEdit() {
  editingId.value = null
  form.value = emptyForm()
  formError.value = ''
}

async function submit() {
  formError.value = ''
  if (!form.value.route_id) {
    formError.value = 'Vyber trasu'
    return
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await api.patch(`/performance/${editingId.value}`, form.value)
      cancelEdit()
    } else {
      await api.post('/performance', form.value)
      form.value.note = ''
      form.value.confirmed = false
      form.value.extra_fields = {}
    }
    await loadEntries()
  } catch (e) {
    const message = e instanceof Error ? e.message : 'Nepodařilo se uložit'
    // Pokud už na tuto trasu a den záznam existuje a smím ho upravit, rovnou tam přepneme.
    const clash = entries.value.find(
      (en) => en.route_id === form.value.route_id && en.date === form.value.date,
    )
    if (!editingId.value && clash && canEdit(clash)) {
      startEdit(clash)
      formError.value = `${message} Přepnuto do režimu úpravy stávajícího záznamu.`
    } else {
      formError.value = message
    }
  } finally {
    submitting.value = false
  }
}

async function toggleLog(entryId: number) {
  if (expandedLogId.value === entryId) {
    expandedLogId.value = null
    return
  }
  expandedLogId.value = entryId
  if (!editLogs.value[entryId]) {
    loadingLog.value = entryId
    try {
      editLogs.value[entryId] = await api.get<EditLogEntry[]>(`/performance/${entryId}/edits`)
    } finally {
      loadingLog.value = null
    }
  }
}

async function submitField() {
  fieldError.value = ''
  if (!newField.value.label.trim()) return
  fieldSubmitting.value = true
  try {
    await api.post('/performance/fields', newField.value)
    newField.value = { label: '', field_type: 'number', required: false }
    await loadFields()
  } catch (e) {
    fieldError.value = e instanceof Error ? e.message : 'Nepodařilo se přidat pole'
  } finally {
    fieldSubmitting.value = false
  }
}

async function toggleFieldActive(f: FieldDef) {
  await api.patch(`/performance/fields/${f.id}`, { active: !f.active })
  await loadFields()
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
  await Promise.all([loadRoutes(), loadFields(), loadUsers()])
  await loadEntries()
  await loadAverages()
})
</script>

<template>
  <div>
    <h1><span class="eyebrow">Denní výkon</span>Formulář na denní výkon</h1>

    <div class="card">
      <h3 style="margin-top:0">{{ editingId ? 'Upravit záznam' : 'Nový záznam' }}</h3>
      <p v-if="editingId" style="font-size:12px;color:var(--muted);margin-top:-8px">
        Upravuješ existující záznam. Pokud ho upravíš jiný den, než na který je, uvidí to admin v přehledu.
      </p>
      <form @submit.prevent="submit">
        <div class="form-row">
          <div class="field">
            <label>Trasa</label>
            <select v-model.number="form.route_id" required>
              <option :value="null" disabled>Vyber trasu</option>
              <option v-for="r in (editingId ? routes : myRoutes)" :key="r.id" :value="r.id">{{ r.name }}</option>
            </select>
            <p v-if="!editingId && !myRoutes.length" style="font-size: 12px; color: var(--muted); margin: 4px 0 0">
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
        <div class="form-row" v-if="activeFields.length">
          <div class="field" v-for="f in activeFields" :key="f.id">
            <label>{{ f.label }}<span v-if="f.required"> *</span></label>
            <input
              v-model="form.extra_fields[f.key]"
              :type="f.field_type === 'number' ? 'number' : 'text'"
              :required="f.required"
            />
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
          {{ submitting ? 'Ukládám…' : editingId ? 'Uložit úpravu' : 'Uložit záznam' }}
        </button>
        <button v-if="editingId" type="button" class="btn secondary" style="margin-left:8px" @click="cancelEdit">
          Zrušit úpravu
        </button>
        <p v-if="formError" class="error">{{ formError }}</p>
      </form>
    </div>

    <div class="card" v-if="isAdmin">
      <h3 style="margin-top:0">Vlastní pole formuláře</h3>
      <p style="font-size:12px;color:var(--muted);margin-top:-8px">
        Přidej si vlastní sloupec do formuláře výkonu (např. počet krabic). Neaktivní pole zůstanou
        zachovaná u starých záznamů, jen zmizí z formuláře a tabulky.
      </p>
      <form @submit.prevent="submitField" style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:14px">
        <div class="field" style="margin:0;flex:1;min-width:160px">
          <label>Název pole</label>
          <input v-model="newField.label" placeholder="např. Počet krabic" />
        </div>
        <div class="field" style="margin:0">
          <label>Typ</label>
          <select v-model="newField.field_type">
            <option value="number">Číslo</option>
            <option value="text">Text</option>
          </select>
        </div>
        <div class="field" style="margin:0;display:flex;align-items:center;gap:6px">
          <input id="field-required" type="checkbox" v-model="newField.required" style="width:auto" />
          <label for="field-required" style="margin:0">Povinné</label>
        </div>
        <button class="btn secondary" type="submit" :disabled="fieldSubmitting">
          {{ fieldSubmitting ? 'Přidávám…' : 'Přidat pole' }}
        </button>
      </form>
      <p v-if="fieldError" class="error" style="margin-top:-8px">{{ fieldError }}</p>
      <p v-if="!allFields.length" style="color:var(--muted);margin:0">Zatím nemáš žádná vlastní pole.</p>
      <table v-else>
        <thead>
          <tr><th>Název</th><th>Typ</th><th>Povinné</th><th>Stav</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="f in allFields" :key="f.id">
            <td>{{ f.label }}</td>
            <td>{{ f.field_type === 'number' ? 'číslo' : 'text' }}</td>
            <td>{{ f.required ? 'ano' : 'ne' }}</td>
            <td>
              <span class="badge" :class="f.active ? 'paid' : 'unpaid'">
                {{ f.active ? 'aktivní' : 'neaktivní' }}
              </span>
            </td>
            <td>
              <button class="btn secondary" @click="toggleFieldActive(f)">
                {{ f.active ? 'Deaktivovat' : 'Aktivovat' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
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
        <div class="field" style="margin:0" v-if="isAdmin">
          <label>Kurýr</label>
          <select v-model.number="selectedCourier" @change="loadEntries">
            <option :value="null">Všichni</option>
            <option v-for="u in allUsers" :key="u.id" :value="u.id">
              {{ u.full_name }}{{ u.role === 'admin' ? ' (admin)' : '' }}
            </option>
          </select>
        </div>
        <div class="field" style="margin:0">
          <label>Zobrazit</label>
          <select v-model="filterMode" @change="refreshFiltered">
            <option value="month">Podle měsíce</option>
            <option value="day">Podle konkrétního dne</option>
          </select>
        </div>
        <template v-if="filterMode === 'month'">
          <div class="field" style="margin:0">
            <label>Měsíc</label>
            <input v-model.number="filterMonth" type="number" min="1" max="12" @change="refreshFiltered" style="width:80px" />
          </div>
          <div class="field" style="margin:0">
            <label>Rok</label>
            <input v-model.number="filterYear" type="number" @change="refreshFiltered" style="width:100px" />
          </div>
        </template>
        <template v-else>
          <div class="field" style="margin:0">
            <label>Den</label>
            <input v-model="filterDay" type="date" @change="refreshFiltered" />
          </div>
        </template>
        <button v-if="isAdmin" class="btn secondary" @click="exportCsv">Export do CSV</button>
      </div>

      <table>
        <thead>
          <tr>
            <th>Datum</th>
            <th v-if="isAdmin">Kurýr</th>
            <th>Trasa</th><th class="num">Km</th><th class="num">Zásilky</th>
            <th class="num">Hodiny</th>
            <th v-for="f in activeFields" :key="f.id" class="num">{{ f.label }}</th>
            <th>Potvrzeno</th><th>Poznámka</th><th>Úpravy</th><th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="e in entries" :key="e.id">
            <tr :class="{ 'row-holiday': e.is_holiday, 'row-weekend': e.is_weekend && !e.is_holiday }">
              <td>{{ e.date }}</td>
              <td v-if="isAdmin">{{ courierName(e.user_id) }}</td>
              <td>{{ routes.find(r => r.id === e.route_id)?.name || e.route_id }}</td>
              <td class="num">{{ e.km_driven }}</td>
              <td class="num">{{ e.packages_delivered }}</td>
              <td class="num">{{ e.hours_worked }}</td>
              <td v-for="f in activeFields" :key="f.id" class="num">{{ e.extra_fields[f.key] ?? '—' }}</td>
              <td>{{ e.confirmed ? '✓' : '—' }}</td>
              <td>{{ e.note }}</td>
              <td>
                <span v-if="e.is_late_edit" class="badge unpaid">upraveno po termínu</span>
                <span v-else-if="e.edit_count" class="badge paid">upraveno</span>
                <span v-else style="color:var(--muted)">—</span>
              </td>
              <td style="white-space:nowrap">
                <button v-if="canEdit(e)" class="btn secondary" @click="startEdit(e)">Upravit</button>
                <button
                  v-if="isAdmin && e.edit_count"
                  class="btn secondary"
                  style="margin-left:6px"
                  @click="toggleLog(e.id)"
                >
                  {{ expandedLogId === e.id ? 'Skrýt log' : `Log (${e.edit_count})` }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedLogId === e.id">
              <td colspan="100" style="background:var(--paper)">
                <div v-if="loadingLog === e.id" style="font-size:13px;color:var(--muted)">Načítám log…</div>
                <div v-else-if="!editLogs[e.id]?.length" style="font-size:13px;color:var(--muted)">
                  Zatím žádné úpravy.
                </div>
                <ul v-else style="list-style:none;margin:0;padding:0;font-size:13px">
                  <li
                    v-for="log in editLogs[e.id]"
                    :key="log.id"
                    style="padding:8px 0;border-bottom:1px solid var(--border)"
                  >
                    <strong>{{ log.edited_by_name }}</strong>
                    · {{ new Date(log.edited_at).toLocaleString('cs-CZ') }}
                    <ul style="margin:4px 0 0;padding-left:18px">
                      <li v-for="(change, field) in log.changes" :key="field">
                        {{ fieldLabels[field] || field }}:
                        <code>{{ formatChangeValue(field, change.old) }}</code> →
                        <code>{{ formatChangeValue(field, change.new) }}</code>
                      </li>
                    </ul>
                  </li>
                </ul>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p style="font-size:12px;color:var(--muted);margin:10px 0 0">
        <span class="legend-swatch row-weekend"></span> víkend &nbsp;
        <span class="legend-swatch row-holiday"></span> státní svátek
      </p>
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
