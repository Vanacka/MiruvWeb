<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

interface Checklist {
  date: string
  car_checked: boolean
  refueled: boolean
  form_filled: boolean
  on_vacation: boolean
}

const { user } = useAuth()
const checklist = ref<Checklist | null>(null)
const savingField = ref<'car_checked' | 'refueled' | null>(null)

const todayLabel = computed(() =>
  new Date().toLocaleDateString('cs-CZ', { weekday: 'long', day: 'numeric', month: 'long' }),
)

const doneCount = computed(() => {
  if (!checklist.value) return 0
  return [checklist.value.car_checked, checklist.value.refueled, checklist.value.form_filled].filter(
    Boolean,
  ).length
})

async function load() {
  checklist.value = await api.get<Checklist>('/checklist/today')
}

async function toggle(field: 'car_checked' | 'refueled') {
  if (!checklist.value || savingField.value) return
  const next = !checklist.value[field]
  checklist.value[field] = next
  savingField.value = field
  try {
    checklist.value = await api.patch<Checklist>('/checklist/today', { [field]: next })
  } catch {
    checklist.value[field] = !next
  } finally {
    savingField.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1><span class="eyebrow">Dnešní směna</span>Ahoj, {{ user?.full_name }}</h1>
    <p class="today-date">{{ todayLabel }}</p>

    <div class="card vacation-card" v-if="checklist?.on_vacation">
      <h3 style="margin-top: 0">Dnes máš dovolenou</h3>
      <p style="margin: 0; color: var(--muted)">Žádné úkoly na dnešek nemáš, užij si volno.</p>
    </div>

    <div class="card checklist-card" v-else-if="checklist">
      <div class="checklist-header">
        <h3>Úkoly na dnešní den</h3>
        <span class="checklist-progress">{{ doneCount }}/3 hotovo</span>
      </div>

      <ul class="checklist">
        <li class="checklist-item" :class="{ done: checklist.car_checked }">
          <button
            type="button"
            class="check-toggle"
            :disabled="savingField === 'car_checked'"
            @click="toggle('car_checked')"
          >
            <span class="check-box" :class="{ checked: checklist.car_checked }"></span>
            <span class="check-label">Zkontrolovat auto</span>
          </button>
        </li>

        <li class="checklist-item" :class="{ done: checklist.refueled }">
          <button
            type="button"
            class="check-toggle"
            :disabled="savingField === 'refueled'"
            @click="toggle('refueled')"
          >
            <span class="check-box" :class="{ checked: checklist.refueled }"></span>
            <span class="check-label">Natankovat</span>
          </button>
        </li>

        <li class="checklist-item" :class="{ done: checklist.form_filled }">
          <router-link to="/vykon" class="check-toggle">
            <span class="check-box" :class="{ checked: checklist.form_filled }"></span>
            <span class="check-label">
              Vyplnit formulář trasy
              <span class="check-hint">
                {{
                  checklist.form_filled
                    ? 'Dnes už vyplněno'
                    : 'Odškrtne se, až formulář výkonu vyplníš celý bez přeskočení'
                }}
              </span>
            </span>
          </router-link>
        </li>
      </ul>
    </div>

    <div class="card" v-else>Načítám úkoly…</div>
  </div>
</template>
