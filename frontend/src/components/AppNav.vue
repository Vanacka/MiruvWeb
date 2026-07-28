<script setup lang="ts">
import { useAuth } from '../stores/auth'

const { user, logout } = useAuth()
</script>

<template>
  <aside class="sidebar">
    <div class="brand">MiruvWeb</div>
    <router-link to="/">Nafta</router-link>
    <router-link to="/dovolena">Dovolená</router-link>
    <router-link to="/vykon">Denní výkon</router-link>
    <router-link v-if="user?.role === 'admin'" to="/zamestnanci">Zaměstnanci</router-link>
    <div class="user-box" v-if="user">
      {{ user.full_name }} · {{ user.role === 'admin' ? 'admin' : 'kurýr' }}
      <br />
      <button class="logout" @click="logout">Odhlásit se</button>
    </div>
  </aside>
</template>
