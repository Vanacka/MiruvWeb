<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api/client'

interface User {
  id: number
  username: string
  full_name: string
  role: 'admin' | 'courier'
  vacation_days_limit: number
}

const users = ref<User[]>([])
const form = ref({
  username: '',
  password: '',
  full_name: '',
  role: 'courier' as 'admin' | 'courier',
  vacation_days_limit: 20,
})
const submitting = ref(false)
const error = ref('')
const success = ref('')

async function load() {
  users.value = await api.get<User[]>('/auth/users')
}

async function submit() {
  error.value = ''
  success.value = ''
  submitting.value = true
  try {
    await api.post('/auth/users', form.value)
    success.value = `Účet pro ${form.value.full_name} byl vytvořen.`
    form.value = { username: '', password: '', full_name: '', role: 'courier', vacation_days_limit: 20 }
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Nepodařilo se založit účet'
  } finally {
    submitting.value = false
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
        <button class="btn" type="submit" :disabled="submitting">
          {{ submitting ? 'Zakládám…' : 'Založit účet' }}
        </button>
        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="success" style="color: var(--green); font-size: 13px; margin-top: 8px">{{ success }}</p>
      </form>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Přehled účtů</h3>
      <table>
        <thead>
          <tr><th>Jméno</th><th>Login</th><th>Role</th><th class="num">Limit dovolené</th></tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.full_name }}</td>
            <td>{{ u.username }}</td>
            <td>{{ u.role === 'admin' ? 'admin' : 'kurýr' }}</td>
            <td class="num">{{ u.vacation_days_limit }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
