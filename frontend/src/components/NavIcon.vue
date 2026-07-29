<script setup lang="ts">
defineProps<{ name: 'home' | 'fuel' | 'vacation' | 'performance' | 'people' }>()
</script>

<template>
  <svg
    v-if="name === 'home'"
    viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
  >
    <path d="M3 11.5 12 4l9 7.5" />
    <path d="M5.5 10v9a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-9" />
    <path d="M9.5 20v-6h5v6" />
  </svg>
  <svg
    v-else-if="name === 'fuel'"
    viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
  >
    <path d="M4 20V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v14" />
    <path d="M4 20h10" />
    <path d="M14 9h2l3 3v5.5a1.5 1.5 0 0 1-3 0V15a1 1 0 0 0-1-1h-1" />
    <path d="M7 6h3" />
  </svg>
  <svg
    v-else-if="name === 'vacation'"
    viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
  >
    <rect x="3.5" y="5" width="17" height="15" rx="2" />
    <path d="M3.5 9.5h17" />
    <path d="M8 3v4M16 3v4" />
  </svg>
  <svg
    v-else-if="name === 'performance'"
    viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
  >
    <path d="M4 19V5" />
    <path d="M4 19h16" />
    <path d="M8 15v-4M12.5 15V8M17 15v-6" />
  </svg>
  <svg
    v-else-if="name === 'people'"
    viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
  >
    <circle cx="9" cy="8" r="3" />
    <path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
    <circle cx="17" cy="9" r="2.3" />
    <path d="M15 19c.2-2.2 1.6-3.8 3.5-4.3" />
  </svg>
</template>