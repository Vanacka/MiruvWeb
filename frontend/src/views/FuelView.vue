<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

interface FuelEntry {
  id: number
  user_id: number
  date: string
  liters: number
  total_price: number
  license_plate: string
  receipt_photo_path: string | null
  status: 'paid' | 'unpaid'
}
interface SummaryItem {
  user_id: number
  full_name: string
  total_liters: number
  total_price: number
  unpaid_price: number
}
interface UserOption { id: number; full_name: string; role: 'admin' | 'courier' }

const { user } = useAuth()
const isAdmin = computed(() => user.value?.role === 'admin')

const entries = ref<FuelEntry[]>([])
const summary = ref<SummaryItem[]>([])
const allUsers = ref<UserOption[]>([])
const expanded = ref<Set<number>>(new Set())

function courierName(userId: number) {
  return allUsers.value.find((u) => u.id === userId)?.full_name || `#${userId}`
}

const date = ref(new Date().toISOString().slice(0, 10))
const liters = ref<number | null>(null)
const totalPrice = ref<number | null>(null)
const licensePlate = ref('')
const receiptFile = ref<File | null>(null)
const submitting = ref(false)
const formError = ref('')

async function load() {
  entries.value = await api.get<FuelEntry[]>('/fuel')
  if (isAdmin.value) {
    summary.value = await api.get<SummaryItem[]>('/fuel/summary')
    allUsers.value = await api.get<UserOption[]>('/auth/users')
  }
}

function toggle(id: number) {
  expanded.value.has(id) ? expanded.value.delete(id) : expanded.value.add(id)
}

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  receiptFile.value = target.files?.[0] || null
}

async function submit() {
  formError.value = ''
  if (!receiptFile.value) {
    formError.value = 'Nahraj prosím fotku účtenky'
    return
  }
  submitting.value = true
  try {
    const form = new FormData()
    form.set('date', date.value)
    form.set('liters', String(liters.value))
    form.set('total_price', String(totalPrice.value))
    form.set('license_plate', licensePlate.value)
    form.set('receipt', receiptFile.value)
    await api.post('/fuel', form)
    liters.value = null
    totalPrice.value = null
    licensePlate.value = ''
    receiptFile.value = null
    await load()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : 'Nepodařilo se uložit'
  } finally {
    submitting.value = false
  }
}

async function toggleStatus(entry: FuelEntry) {
  const newStatus = entry.status === 'paid' ? 'unpaid' : 'paid'
  await api.patch(`/fuel/${entry.id}/status?status=${newStatus}`)
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <h1><span class="eyebrow">Nafta</span>Proplacení nafty</h1>

    <div class="card">
      <h3 style="margin-top:0">Nová položka</h3>
      <form @submit.prevent="submit">
        <div class="form-row">
          <div class="field">
            <label>Datum</label>
            <input v-model="date" type="date" required />
          </div>
          <div class="field">
            <label>SPZ</label>
            <input v-model="licensePlate" required placeholder="1AB 2345" />
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label>Počet litrů</label>
            <input v-model.number="liters" type="number" step="0.01" required />
          </div>
          <div class="field">
            <label>Celková cena (Kč)</label>
            <input v-model.number="totalPrice" type="number" step="0.01" required />
          </div>
        </div>
        <div class="field">
          <label>Fotka účtenky</label>
          <input type="file" accept="image/*" @change="onFileChange" required />
        </div>
        <button class="btn" type="submit" :disabled="submitting">
          {{ submitting ? 'Ukládám…' : 'Uložit' }}
        </button>
        <p v-if="formError" class="error">{{ formError }}</p>
      </form>
    </div>

    <div class="card" v-if="isAdmin && summary.length">
      <h3 style="margin-top:0">Celkový přehled po lidech</h3>
      <table>
        <thead>
          <tr><th>Kurýr</th><th class="num">Litry</th><th class="num">Celkem Kč</th><th class="num">Neproplaceno</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in summary" :key="s.user_id">
            <td>{{ s.full_name }}</td>
            <td class="num">{{ s.total_liters.toFixed(1) }}</td>
            <td class="num">{{ s.total_price.toFixed(0) }}</td>
            <td class="num">{{ s.unpaid_price.toFixed(0) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Položky</h3>
      <table>
        <thead>
          <tr>
            <th>Datum</th><th v-if="isAdmin">Kurýr</th><th>SPZ</th><th class="num">Litry</th><th class="num">Cena</th><th>Stav</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="e in entries" :key="e.id">
            <tr @click="toggle(e.id)" style="cursor:pointer">
              <td>{{ e.date }}</td>
              <td v-if="isAdmin">{{ courierName(e.user_id) }}</td>
              <td>{{ e.license_plate }}</td>
              <td class="num">{{ e.liters }}</td>
              <td class="num">{{ e.total_price }}</td>
              <td>
                <span class="badge" :class="e.status">
                  {{ e.status === 'paid' ? 'proplaceno' : 'neproplaceno' }}
                </span>
              </td>
            </tr>
            <tr v-if="expanded.has(e.id)">
              <td :colspan="isAdmin ? 6 : 5" style="background:var(--paper)">
                <div v-if="e.receipt_photo_path" style="margin-bottom:10px">
                  <img :src="`${api.API_URL}/${e.receipt_photo_path}`" style="max-width:220px;border-radius:6px" />
                </div>
                <button v-if="isAdmin" class="btn secondary" @click.stop="toggleStatus(e)">
                  Označit jako {{ e.status === 'paid' ? 'neproplaceno' : 'proplaceno' }}
                </button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
