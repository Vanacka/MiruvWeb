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
  skipped_fields: string[]
  is_weekend: boolean
  is_holiday: boolean
  edit_count: number
  is_late_creation: boolean
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
interface Step {
  key: string
  label: string
  required: boolean
  field_type: 'number' | 'text'
}
interface Dispute {
  id: number
  route_id: number
  route_name: string
  date: string
  status: 'pending' | 'approved' | 'rejected'
  reported_by_id: number
  reported_by_name: string
  proposed_km_driven: number
  proposed_packages_delivered: number
  proposed_hours_worked: number
  proposed_note: string | null
  proposed_confirmed: boolean
  proposed_extra_fields: Record<string, string | number>
  proposed_skipped_fields: string[]
  conflicting_entry: Entry
  conflicting_entry_owner_name: string
  corrected_route_id: number | null
  corrected_route_name: string | null
  created_at: string
  resolved_at: string | null
  resolved_by_name: string | null
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
const conflict = ref<{ message: string; conflictingEntryId: number } | null>(null)
const disputeSubmitting = ref(false)

// Krokovací "vyplnění formuláře" místo ručního checkboxu - kurýr projde každou
// položku a buď ji vyplní, nebo řekne "vyplním později". Jen pokud nic
// nepřeskočí, označí se záznam jako kompletně vyplněný.
const wizardActive = ref(false)
const currentStep = ref(0)
const skippedFields = ref<Set<string>>(new Set())

// Když kurýr pokračuje v dřív rozpracovaném (nedokončeném) záznamu za dnešek,
// wizard prochází jen položky, které tehdy nechal na později - a nikde se
// nepíše, že jde o "úpravu", aby to nepůsobilo matoucně.
const resuming = ref(false)
const resumeSteps = ref<Step[] | null>(null)
const todayEntry = ref<Entry | null>(null)

// Nahlášená chyba na dnešek počítá jako "za dnešek už je hotovo" stejně jako
// vyplněný záznam - dokud ji admin nevyřídí, nemá smysl znovu nabízet tlačítka
// pro vyplnění/nahlášení, jako by se nic nestalo.
const todayDispute = ref<Dispute | null>(null)

// Když kurýr rozjede wizard nad hlášením chyby (jeho vlastní pending dispute),
// odesílá se přes PATCH na dispute, ne přes POST na nový záznam.
const resumingDispute = ref<number | null>(null)

const reportMode = ref(false)
const reportRouteId = ref<number | null>(null)

const steps = computed<Step[]>(() => [
  { key: 'km_driven', label: 'Kilometry', required: false, field_type: 'number' },
  { key: 'packages_delivered', label: 'Počet zásilek', required: false, field_type: 'number' },
  { key: 'hours_worked', label: 'Odpracované hodiny', required: false, field_type: 'number' },
  ...activeFields.value.map((f) => ({
    key: f.key, label: f.label, required: f.required, field_type: f.field_type,
  })),
  { key: 'note', label: 'Poznámka', required: false, field_type: 'text' },
])

const activeWizardSteps = computed<Step[]>(() => resumeSteps.value ?? steps.value)

const fallbackStep: Step = { key: '', label: '', required: false, field_type: 'text' }
const currentStepDef = computed<Step>(() => activeWizardSteps.value[currentStep.value] ?? fallbackStep)

const showTodayDoneMessage = computed(() =>
  !editingId.value && !resumingDispute.value && (todayEntry.value?.confirmed === true || !!todayDispute.value),
)

// Zpětně vyplňovaný formulář (jiný den než dnešek) nejde nechat nekompletní -
// "vyplním později" u zpětného vyplnění nedává smysl, termín už stejně minul.
const isBackfilling = computed(() => form.value.date !== new Date().toISOString().slice(0, 10))

function getStepValue(step: Step): string | number {
  if (step.key === 'km_driven') return form.value.km_driven
  if (step.key === 'packages_delivered') return form.value.packages_delivered
  if (step.key === 'hours_worked') return form.value.hours_worked
  if (step.key === 'note') return form.value.note
  return form.value.extra_fields[step.key] ?? ''
}

function hasStepValue(step: Step): boolean {
  return String(getStepValue(step)).trim() !== ''
}

function stepDisplayValue(step: Step): string {
  if (skippedFields.value.has(step.key)) return 'doplní se později'
  const value = getStepValue(step)
  return value !== '' && value !== undefined ? String(value) : '—'
}

async function findMyEntryForDate(dateStr: string): Promise<Entry | null> {
  const [y, m, d] = dateStr.split('-').map(Number)
  const params = new URLSearchParams({ year: String(y), month: String(m), day: String(d) })
  if (user.value) params.set('user_id', String(user.value.id))
  const result = await api.get<Entry[]>(`/performance?${params}`)
  return result.find((en) => en.user_id === user.value?.id) ?? null
}

function resumeEntry(entry: Entry) {
  resuming.value = true
  editingId.value = entry.id
  form.value = {
    route_id: entry.route_id,
    date: entry.date,
    km_driven: entry.km_driven,
    packages_delivered: entry.packages_delivered,
    hours_worked: entry.hours_worked,
    note: entry.note || '',
    confirmed: entry.confirmed,
    extra_fields: { ...entry.extra_fields } as Record<string, string>,
  }
  wizardActive.value = true
  currentStep.value = 0
  skippedFields.value = new Set(entry.skipped_fields)
  resumeSteps.value = steps.value.filter((s) => entry.skipped_fields.includes(s.key))
  formError.value = ''
}

// Rozpracované hlášení chyby (dispute) čeká na schválení, takže zatím
// neexistuje žádný Entry k pokračování - draft se drží v samotném disputu.
function resumeDispute(d: Dispute) {
  resuming.value = true
  resumingDispute.value = d.id
  editingId.value = null
  form.value = {
    route_id: d.route_id,
    date: d.date,
    km_driven: d.proposed_km_driven,
    packages_delivered: d.proposed_packages_delivered,
    hours_worked: d.proposed_hours_worked,
    note: d.proposed_note || '',
    confirmed: d.proposed_confirmed,
    extra_fields: { ...d.proposed_extra_fields } as Record<string, string>,
  }
  wizardActive.value = true
  currentStep.value = 0
  skippedFields.value = new Set(d.proposed_skipped_fields)
  resumeSteps.value = steps.value.filter((s) => d.proposed_skipped_fields.includes(s.key))
  formError.value = ''
}

async function findMyPendingDispute(dateStr: string): Promise<Dispute | null> {
  const mine = await api.get<Dispute[]>('/performance/disputes/mine')
  return mine.find((d) => d.date === dateStr && d.status === 'pending') ?? null
}

async function checkTodayEntry() {
  const todayIso = new Date().toISOString().slice(0, 10)
  todayEntry.value = await findMyEntryForDate(todayIso)
  todayDispute.value = null
  if (todayEntry.value && !todayEntry.value.confirmed) {
    resumeEntry(todayEntry.value)
    return
  }
  if (!todayEntry.value) {
    const pendingDispute = await findMyPendingDispute(todayIso)
    if (pendingDispute && pendingDispute.proposed_skipped_fields.length) {
      // Ještě něco chybí vyplnit - rovnou do toho, žádné tlačítko navíc.
      resumeDispute(pendingDispute)
      return
    }
    todayDispute.value = pendingDispute
  }
}

async function startWizard() {
  if (!form.value.route_id) {
    formError.value = 'Vyber trasu'
    return
  }
  formError.value = ''
  const existing = await findMyEntryForDate(form.value.date)
  if (existing) {
    if (existing.confirmed) {
      const routeName = routes.value.find((r) => r.id === existing.route_id)?.name
      formError.value = `Na tento den už máš hotový formulář (trasa ${routeName}).`
      return
    }
    resumeEntry(existing)
    return
  }
  wizardActive.value = true
  currentStep.value = 0
  skippedFields.value = new Set()
  resumeSteps.value = null
  resumingDispute.value = null
}

function exitWizard() {
  if (resuming.value) editingId.value = null
  wizardActive.value = false
  currentStep.value = 0
  skippedFields.value = new Set()
  resumeSteps.value = null
  resuming.value = false
  resumingDispute.value = null
}

function nextStep(skip: boolean) {
  const step = activeWizardSteps.value[currentStep.value]
  if (!step) return
  if (skip) skippedFields.value.add(step.key)
  else skippedFields.value.delete(step.key)
  currentStep.value++
}

function prevStep() {
  if (currentStep.value > 0) currentStep.value--
}

function jumpToStep(i: number) {
  currentStep.value = i
}

// Únikový poklop pro případ, že vlastní trasu kurýr v nabídce nevidí, protože
// ji (omylem) na ten den vyplnil někdo jiný. Jedna akce - vybere trasu, chyba se
// rovnou nahlásí a hned se přepne do vyplňování, žádný mezikrok navíc.
function openReportMode() {
  reportMode.value = true
  reportRouteId.value = null
  formError.value = ''
}

async function submitReportRoute() {
  if (!reportRouteId.value) return
  formError.value = ''
  disputeSubmitting.value = true
  try {
    // Pokud už na tuhle trasu/den čeká vlastní dřívější hlášení (typicky se sem
    // kurýr vrátil znovu), pokračuje se v něm - jinak by se přepsalo prázdným.
    const existing = await findMyPendingDispute(form.value.date)
    const dispute = existing && existing.route_id === reportRouteId.value
      ? existing
      : await api.post<Dispute>('/performance/disputes', {
          route_id: reportRouteId.value,
          date: form.value.date,
          km_driven: 0,
          packages_delivered: 0,
          hours_worked: 0,
          note: null,
          confirmed: false,
          extra_fields: {},
          skipped_fields: steps.value.map((s) => s.key),
        })
    reportMode.value = false
    resumeDispute(dispute)
  } catch (e) {
    formError.value = e instanceof Error ? e.message : 'Nepodařilo se nahlásit chybu'
  } finally {
    disputeSubmitting.value = false
  }
}

const disputes = ref<Dispute[]>([])
const resolveRouteByDispute = ref<Record<number, number | null>>({})
const disputeActionError = ref<Record<number, string>>({})

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

const deletingEntryId = ref<number | null>(null)

async function deleteEntry(e: Entry) {
  if (!window.confirm('Opravdu chceš tento záznam smazat? Nejde to vrátit zpět.')) return
  deletingEntryId.value = e.id
  try {
    await api.delete(`/performance/${e.id}`)
    await loadEntries()
    await loadMyRoutes()
  } catch (err) {
    formError.value = err instanceof Error ? err.message : 'Nepodařilo se smazat záznam'
  } finally {
    deletingEntryId.value = null
  }
}

function formatChangeValue(field: string, value: unknown) {
  if (field === 'route_id') return routes.value.find((r) => r.id === value)?.name ?? value
  if (field === 'confirmed') return value ? 'ano' : 'ne'
  if (field === 'extra_fields') return JSON.stringify(value)
  return value
}

async function loadRoutes() {
  routes.value = await api.get<Route[]>('/performance/routes')
  await loadMyRoutes()
}

// Trasy, které si kurýr smí vybrat pro NOVÝ záznam na form.value.date - obsazené
// (na ten den už má formulář) trasy se sem záměrně nedostanou, viz "Nemohu vybrat
// svoji trasu" níže pro případ, že je obsazená omylem.
async function loadMyRoutes() {
  myRoutes.value = await api.get<Route[]>(`/performance/routes/mine?date=${form.value.date}`)
}

watch(() => form.value.date, () => {
  if (!wizardActive.value && !editingId.value) loadMyRoutes()
})

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

async function loadDisputes() {
  if (!isAdmin.value) return
  disputes.value = await api.get<Dispute[]>('/performance/disputes')
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
  exitWizard()
  resuming.value = false
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
  exitWizard()
}

async function submit(): Promise<boolean> {
  formError.value = ''
  conflict.value = null
  if (!form.value.route_id) {
    formError.value = 'Vyber trasu'
    return false
  }
  submitting.value = true
  const isFlatEdit = editingId.value && !resuming.value
  const payload = isFlatEdit ? form.value : { ...form.value, skipped_fields: [...skippedFields.value] }
  try {
    if (editingId.value) {
      await api.patch(`/performance/${editingId.value}`, payload)
      cancelEdit()
    } else {
      await api.post('/performance', payload)
      form.value = emptyForm()
    }
    await loadEntries()
    await loadMyRoutes()
    return true
  } catch (e) {
    const status = (e as { status?: number }).status
    const detail = (e as { detail?: { message: string; conflicting_entry_id: number; is_mine: boolean } }).detail
    const message = e instanceof Error ? e.message : 'Nepodařilo se uložit'

    if (!editingId.value && status === 409 && detail) {
      if (detail.is_mine) {
        const clash = entries.value.find((en) => en.id === detail.conflicting_entry_id)
        if (clash) {
          startEdit(clash)
          formError.value = `${message} Přepnuto do režimu úpravy.`
        } else {
          formError.value = message
        }
      } else {
        conflict.value = { message: detail.message, conflictingEntryId: detail.conflicting_entry_id }
      }
    } else {
      formError.value = message
    }
    return false
  } finally {
    submitting.value = false
  }
}

async function finalizeSubmit() {
  // Doplňování rozpracovaného hlášení chyby (viz "Nemohu vybrat svoji trasu") se
  // ukládá rovnou přes dispute PATCH - zkoušet normální POST /performance by tu
  // jen znovu narazilo na tutéž kolizi a ukázalo zbytečné druhé tlačítko navíc.
  if (resumingDispute.value) {
    await submitDispute()
    return
  }
  const ok = await submit()
  // Při konfliktu (409 - trasu už vyplnil někdo jiný) wizard schválně NEresetujeme -
  // ať se neztratí, co kurýr už vyplnil/přeskočil, než stihne nahlásit chybu.
  if (ok) {
    exitWizard()
    await checkTodayEntry()
  }
}

function onFormSubmit() {
  if (editingId.value && !resuming.value) {
    submit()
  } else if (wizardActive.value && currentStep.value >= activeWizardSteps.value.length) {
    finalizeSubmit()
  }
}

async function submitDispute() {
  if (!form.value.route_id) return
  disputeSubmitting.value = true
  formError.value = ''
  const payload = { ...form.value, skipped_fields: [...skippedFields.value] }
  try {
    if (resumingDispute.value) {
      await api.patch<Dispute>(`/performance/disputes/${resumingDispute.value}`, payload)
    } else {
      await api.post<Dispute>('/performance/disputes', payload)
    }
    conflict.value = null
    exitWizard()
    form.value = emptyForm()
    await checkTodayEntry()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : 'Nepodařilo se nahlásit chybu'
  } finally {
    disputeSubmitting.value = false
  }
}

async function approveDispute(d: Dispute) {
  const correctedRouteId = resolveRouteByDispute.value[d.id]
  if (!correctedRouteId) {
    disputeActionError.value[d.id] = 'Vyber, na jakou trasu se má přesunout původní záznam.'
    return
  }
  disputeActionError.value[d.id] = ''
  try {
    await api.post(`/performance/disputes/${d.id}/approve`, { corrected_route_id: correctedRouteId })
    await Promise.all([loadDisputes(), loadEntries()])
  } catch (e) {
    disputeActionError.value[d.id] = e instanceof Error ? e.message : 'Nepodařilo se schválit'
  }
}

async function rejectDispute(d: Dispute) {
  try {
    await api.post(`/performance/disputes/${d.id}/reject`)
    await loadDisputes()
  } catch (e) {
    disputeActionError.value[d.id] = e instanceof Error ? e.message : 'Nepodařilo se zamítnout'
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
  await Promise.all([loadRoutes(), loadFields(), loadUsers(), loadDisputes()])
  await loadEntries()
  await loadAverages()
  await checkTodayEntry()
})
</script>

<template>
  <div>
    <h1><span class="eyebrow">Denní výkon</span>Formulář na denní výkon</h1>

    <div class="card" v-if="showTodayDoneMessage">
      <h3 style="margin-top:0">Dnešní formulář</h3>
      <p v-if="todayEntry?.confirmed" style="margin:0">
        Dnes už jsi vyplnil formulář na trasu
        <strong>{{ routes.find(r => r.id === todayEntry!.route_id)?.name }}</strong>.
        Případnou úpravu uděláš v tabulce záznamů níže.
      </p>
      <template v-else-if="todayDispute">
        <p style="margin:0">
          Dnes jsi nahlásil chybu na trase <strong>{{ todayDispute.route_name }}</strong> -
          čeká na schválení adminem.
        </p>
      </template>
    </div>

    <div class="card" v-else>
      <h3 style="margin-top:0">
        {{ resumingDispute ? 'Nahlášení chyby na trase' : editingId && !resuming ? 'Upravit záznam' : 'Nový záznam' }}
      </h3>
      <p v-if="resumingDispute" style="font-size:12px;color:var(--muted);margin-top:-8px">
        Vyplňuješ, co ti patří na tuto trasu/den - admin to porovná s chybným záznamem a rozhodne o opravě.
      </p>
      <p v-if="editingId && !resuming" style="font-size:12px;color:var(--muted);margin-top:-8px">
        Upravuješ existující záznam. Pokud ho upravíš jiný den, než na který je, uvidí to admin v přehledu.
      </p>
      <form @submit.prevent="onFormSubmit">
        <div class="form-row">
          <div class="field" v-if="!reportMode">
            <label>Trasa</label>
            <select v-model.number="form.route_id" required :disabled="wizardActive">
              <option :value="null" disabled>Vyber trasu</option>
              <option v-for="r in (editingId || wizardActive ? routes : myRoutes)" :key="r.id" :value="r.id">{{ r.name }}</option>
            </select>
            <p v-if="!editingId && !myRoutes.length && !routes.length" style="font-size: 12px; color: var(--muted); margin: 4px 0 0">
              Zatím nejsou založené žádné trasy.
            </p>
            <p v-if="!editingId && !wizardActive" style="font-size:12px;margin:6px 0 0">
              <button type="button" class="btn secondary" @click="openReportMode">Nemohu vybrat svoji trasu</button>
            </p>
          </div>
          <div class="field" v-else>
            <label>Na jakou trasu jsi měl/a dnes jet?</label>
            <select v-model.number="reportRouteId">
              <option :value="null" disabled>Vyber trasu</option>
              <option v-for="r in routes" :key="r.id" :value="r.id">{{ r.name }}</option>
            </select>
            <div style="display:flex;gap:8px;margin-top:8px">
              <button type="button" class="btn" :disabled="!reportRouteId || disputeSubmitting" @click="submitReportRoute">
                {{ disputeSubmitting ? 'Nahlašuji…' : 'Nahlásit a pokračovat' }}
              </button>
              <button type="button" class="btn secondary" @click="reportMode = false">Zpět</button>
            </div>
          </div>
          <div class="field">
            <label>Datum</label>
            <input v-model="form.date" type="date" required :disabled="wizardActive" />
          </div>
        </div>

        <!-- Úprava existujícího záznamu: klasický plochý formulář -->
        <template v-if="editingId && !resuming">
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
          <button class="btn" type="submit" :disabled="submitting">
            {{ submitting ? 'Ukládám…' : 'Uložit úpravu' }}
          </button>
          <button type="button" class="btn secondary" style="margin-left:8px" @click="cancelEdit">
            Zrušit úpravu
          </button>
        </template>

        <!-- Nový záznam: postupné krokování polí místo ručního checkboxu.
             V reportMode (výběr trasy k nahlášení) se schválně nevykresluje nic
             z tohohle - jen picker + Datum výš, dokud se trasa nepotvrdí. -->
        <template v-else-if="!reportMode">
          <div v-if="!wizardActive">
            <button type="button" class="btn" @click="startWizard">Pokračovat k vyplnění formuláře</button>
          </div>

          <div v-else-if="currentStep < activeWizardSteps.length" class="field" style="border-top:1px solid var(--border);padding-top:14px">
            <p style="font-size:12px;color:var(--muted);margin:0 0 8px">
              Krok {{ currentStep + 1 }} / {{ activeWizardSteps.length }}
            </p>
            <label>{{ currentStepDef.label }}<span v-if="currentStepDef.required"> *</span></label>
            <input
              v-if="currentStepDef.key === 'km_driven'"
              v-model.number="form.km_driven"
              type="number"
              step="0.1"
            />
            <input
              v-else-if="currentStepDef.key === 'packages_delivered'"
              v-model.number="form.packages_delivered"
              type="number"
            />
            <input
              v-else-if="currentStepDef.key === 'hours_worked'"
              v-model.number="form.hours_worked"
              type="number"
              step="0.1"
            />
            <input v-else-if="currentStepDef.key === 'note'" v-model="form.note" />
            <input
              v-else
              v-model="form.extra_fields[currentStepDef.key]"
              :type="currentStepDef.field_type === 'number' ? 'number' : 'text'"
            />
            <p v-if="(currentStepDef.required || isBackfilling) && !hasStepValue(currentStepDef)" style="font-size:12px;color:var(--muted);margin:6px 0 0">
              {{ isBackfilling ? 'Zpětně vyplňovaný formulář nejde nechat neúplný, musíš ho vyplnit.' : 'Toto pole je povinné, musíš ho vyplnit.' }}
            </p>
            <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
              <button
                type="button"
                class="btn"
                :disabled="(currentStepDef.required || isBackfilling) && !hasStepValue(currentStepDef)"
                @click="nextStep(false)"
              >
                Pokračovat
              </button>
              <button
                v-if="!currentStepDef.required && !isBackfilling"
                type="button"
                class="btn secondary"
                @click="nextStep(true)"
              >
                Vyplnit později
              </button>
              <button v-if="currentStep > 0" type="button" class="btn secondary" @click="prevStep">Zpět</button>
              <button v-if="!resuming" type="button" class="btn secondary" @click="exitWizard">Zrušit</button>
            </div>
          </div>

          <div v-else class="field" style="border-top:1px solid var(--border);padding-top:14px">
            <p style="font-weight:600;margin:0 0 8px">Shrnutí před uložením</p>
            <ul style="list-style:none;margin:0 0 10px;padding:0;font-size:14px">
              <li
                v-for="(s, i) in activeWizardSteps"
                :key="s.key"
                style="display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid var(--border)"
              >
                <span>{{ s.label }}: <strong>{{ stepDisplayValue(s) }}</strong></span>
                <button type="button" class="btn secondary" @click="jumpToStep(i)">Upravit</button>
              </li>
            </ul>
            <p v-if="skippedFields.size" style="font-size:12px;color:var(--muted);margin:0 0 10px">
              Něco jsi nechal na později - formulář se uloží jako nekompletní a adminovi přijde upozornění.
            </p>
            <button class="btn" type="submit" :disabled="submitting || disputeSubmitting">
              {{ (submitting || disputeSubmitting) ? 'Odesílám…' : resumingDispute ? 'Odeslat hlášení' : 'Uložit záznam' }}
            </button>
            <button v-if="!resuming" type="button" class="btn secondary" style="margin-left:8px" @click="exitWizard">
              Zrušit
            </button>
          </div>
        </template>

        <p v-if="formError" class="error">{{ formError }}</p>
      </form>

      <div v-if="conflict" class="card" style="margin:14px 0 0;border-color:var(--red);background:#fdeeee">
        <p style="margin:0 0 10px">{{ conflict.message }}</p>
        <button class="btn" type="button" :disabled="disputeSubmitting" @click="submitDispute">
          {{ disputeSubmitting ? 'Odesílám…' : 'Nahlásit chybu / vyžádat opravu' }}
        </button>
        <button class="btn secondary" type="button" style="margin-left:8px" @click="conflict = null">
          Zrušit
        </button>
      </div>
    </div>

    <div class="card" v-if="isAdmin && disputes.filter(d => d.status === 'pending').length">
      <h3 style="margin-top:0">Nahlášené chyby</h3>
      <p style="font-size:12px;color:var(--muted);margin-top:-8px">
        Kurýr nahlásil, že na tuto trasu/den už omylem vyplnil formulář někdo jiný. Vyber, na jakou
        trasu se má přesunout původní (chybný) záznam, a schval - teprve pak se obě strany opraví.
      </p>
      <div
        v-for="d in disputes.filter(x => x.status === 'pending')"
        :key="d.id"
        style="border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:12px"
      >
        <p style="margin:0 0 8px">
          <strong>{{ d.route_name }}</strong> · {{ d.date }}
        </p>
        <div class="form-row">
          <div>
            <p style="font-size:12px;color:var(--muted);margin:0 0 4px">
              Původní záznam (vyplnil {{ d.conflicting_entry_owner_name }})
            </p>
            <p style="font-size:13px;margin:0">
              {{ d.conflicting_entry.km_driven }} km · {{ d.conflicting_entry.packages_delivered }} zásilek ·
              {{ d.conflicting_entry.hours_worked }} h
              <span v-if="d.conflicting_entry.note"> · „{{ d.conflicting_entry.note }}“</span>
            </p>
          </div>
          <div>
            <p style="font-size:12px;color:var(--muted);margin:0 0 4px">
              Nahlásil {{ d.reported_by_name }} (tvrdí, že tohle patří na {{ d.route_name }})
            </p>
            <p style="font-size:13px;margin:0">
              {{ d.proposed_km_driven }} km · {{ d.proposed_packages_delivered }} zásilek ·
              {{ d.proposed_hours_worked }} h
              <span v-if="d.proposed_note"> · „{{ d.proposed_note }}“</span>
            </p>
          </div>
        </div>
        <div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-top:10px">
          <div class="field" style="margin:0">
            <label>Opravit trasu u {{ d.conflicting_entry_owner_name }} na</label>
            <select v-model.number="resolveRouteByDispute[d.id]">
              <option :value="null" disabled>Vyber správnou trasu</option>
              <option v-for="r in routes.filter(x => x.id !== d.route_id)" :key="r.id" :value="r.id">
                {{ r.name }}
              </option>
            </select>
          </div>
          <button class="btn" type="button" @click="approveDispute(d)">Schválit</button>
          <button class="btn secondary" type="button" @click="rejectDispute(d)">Zamítnout</button>
        </div>
        <p v-if="disputeActionError[d.id]" class="error" style="margin-top:8px">{{ disputeActionError[d.id] }}</p>
      </div>
    </div>

    <div class="card" v-if="isAdmin && disputes.filter(d => d.status !== 'pending').length">
      <h3 style="margin-top:0">Vyřízené spory</h3>
      <table>
        <thead>
          <tr><th>Trasa</th><th>Datum</th><th>Nahlásil</th><th>Stav</th><th>Vyřídil</th></tr>
        </thead>
        <tbody>
          <tr v-for="d in disputes.filter(x => x.status !== 'pending')" :key="d.id">
            <td>{{ d.route_name }}</td>
            <td>{{ d.date }}</td>
            <td>{{ d.reported_by_name }}</td>
            <td>
              <span class="badge" :class="d.status === 'approved' ? 'paid' : 'unpaid'">
                {{ d.status === 'approved' ? 'schváleno' : 'zamítnuto' }}
              </span>
              <span v-if="d.corrected_route_name"> → {{ d.corrected_route_name }}</span>
            </td>
            <td>{{ d.resolved_by_name }}</td>
          </tr>
        </tbody>
      </table>
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
            <th>Potvrzeno</th><th>Poznámka</th><th>Po termínu</th><th></th>
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
                <span v-if="e.is_late_creation" class="badge unpaid">vyplněno</span>
                <span v-else-if="e.is_late_edit" class="badge unpaid">upraveno</span>
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
                <button
                  v-if="canEdit(e)"
                  class="btn secondary"
                  style="margin-left:6px;color:var(--red)"
                  :disabled="deletingEntryId === e.id"
                  @click="deleteEntry(e)"
                >
                  {{ deletingEntryId === e.id ? 'Mažu…' : 'Smazat' }}
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
