<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from '../api/client'
import { useAuth } from '../stores/auth'

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const router = useRouter()
const { fetchMe } = useAuth()

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await login(username.value, password.value)
    await fetchMe()
    router.push('/')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Přihlášení se nezdařilo'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-screen">
    <form class="login-card" @submit.prevent="submit">
      <h1 style="margin-bottom: 20px">Přihlášení</h1>
      <div class="field">
        <label>Uživatelské jméno</label>
        <input v-model="username" autocomplete="username" required />
      </div>
      <div class="field">
        <label>Heslo</label>
        <input v-model="password" type="password" autocomplete="current-password" required />
      </div>
      <button class="btn" type="submit" :disabled="loading" style="width: 100%">
        {{ loading ? 'Přihlašuji…' : 'Přihlásit se' }}
      </button>
      <p v-if="error" class="error">{{ error }}</p>
    </form>
  </div>
</template>
