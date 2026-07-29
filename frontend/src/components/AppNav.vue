<script setup lang="ts">
import { useAuth } from '../stores/auth'
import NavIcon from './NavIcon.vue'
import NotificationsBell from './NotificationsBell.vue'

const { user, logout } = useAuth()

const navItems = [
  { to: '/', label: 'Domů', icon: 'home' as const },
  { to: '/nafta', label: 'Nafta', icon: 'fuel' as const },
  { to: '/dovolena', label: 'Dovolená', icon: 'vacation' as const },
  { to: '/vykon', label: 'Výkon', icon: 'performance' as const },
]
</script>

<template>
  <header class="topbar">
    <div class="brand">MiruvWeb</div>
    <div class="user-chip" v-if="user">
      <NotificationsBell v-if="user.role === 'admin'" />
      <span>{{ user.full_name }}</span>
      <button class="logout" @click="logout">Odhlásit</button>
    </div>
  </header>

  <aside class="sidebar">
    <div class="brand">MiruvWeb</div>
    <router-link v-for="item in navItems" :key="item.to" :to="item.to">{{ item.label }}</router-link>
    <router-link v-if="user?.role === 'admin'" to="/zamestnanci">Zaměstnanci</router-link>
    <div class="user-box" v-if="user">
      {{ user.full_name }} · {{ user.role === 'admin' ? 'admin' : 'kurýr' }}
      <br />
      <button class="logout" @click="logout">Odhlásit se</button>
    </div>
  </aside>

  <NotificationsBell v-if="user?.role === 'admin'" class="desktop-bell" />

  <nav class="bottom-nav">
    <router-link v-for="item in navItems" :key="item.to" :to="item.to" class="bottom-nav-item">
      <NavIcon :name="item.icon" />
      <span class="label">{{ item.label }}</span>
    </router-link>
    <router-link v-if="user?.role === 'admin'" to="/zamestnanci" class="bottom-nav-item">
      <NavIcon name="people" />
      <span class="label">Lidé</span>
    </router-link>
  </nav>
</template>
