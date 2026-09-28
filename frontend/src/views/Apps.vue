<script setup>
import { computed, onMounted, ref } from 'vue'
import { act, api, coverUrl } from '../api'
import AppEditor from '../components/AppEditor.vue'

const profiles = ref([])
const current = ref('')
const emulators = ref([])
const baseCreateJson = ref('')
const sessions = ref(0)
const editing = ref(undefined) // undefined = closed, null = new app
const error = ref('')

const profile = computed(() => profiles.value.find(p => p.id === current.value))
const emuName = id => emulators.value.find(e => e.id === id)?.name || id

async function load() {
  try {
    const [p, e, o] = await Promise.all([api.get('/profiles'), api.get('/emulators'), api.get('/overview')])
    profiles.value = p.profiles
    emulators.value = e.emulators
    baseCreateJson.value = e.base_create_json
    sessions.value = o.sessions.length
    if (!current.value) current.value = (p.profiles.find(x => x.moonlight) || p.profiles[0])?.id
    error.value = ''
  } catch (err) {
    error.value = err.message
  }
}

function imagePresent(app) {
  const emu = emulators.value.find(e => e.image === app.image)
  return emu ? emu.image_info.present : null
}

function confirmRestart(what) {
  return !sessions.value || confirm(`${what} redémarre Wolf : ${sessions.value} session(s) seront coupées. Continuer ?`)
}

async function remove(app) {
  if (!confirm(`Supprimer « ${app.title} » de Wolf ?`) || !confirmRestart('La suppression')) return
  await act('Suppression', () => api.del(`/profiles/${current.value}/apps/${app.index}`), 'Application supprimée')
  load()
}

async function move(app, delta) {
  if (!confirmRestart('Le changement d\'ordre')) return
  await act('Réorganisation', () => api.post(`/profiles/${current.value}/apps/${app.index}/move`, { delta }))
  load()
}

function saved() {
  editing.value = undefined
  load()
}

onMounted(load)
</script>

<template>
  <div class="page-head">
    <h1>Applications</h1>
    <select v-model="current" style="width:auto">
      <option v-for="p in profiles" :key="p.id" :value="p.id">
        {{ p.moonlight ? '🌙 Moonlight (appareils appairés)' : `Profil « ${p.name} »` }}
      </option>
    </select>
    <div class="spacer"></div>
    <button class="primary" @click="editing = null">＋ Nouvelle application</button>
  </div>
  <div v-if="error" class="alert bad">{{ error }}</div>
  <div v-if="profile && !profile.moonlight" class="alert info" style="margin-bottom:16px">
    Ce profil n'est pas visible par les appareils Moonlight (profil de l'interface Wolf UI).
  </div>

  <div v-if="profile" class="grid cols-4">
    <div v-for="app in profile.apps" :key="app.index + app.title" class="card" style="padding:12px">
      <img v-if="app.icon" :src="coverUrl(app.icon)" class="cover" alt="" loading="lazy" />
      <div v-else class="cover placeholder">🎮</div>
      <div style="margin-top:10px">
        <div class="row between">
          <h3>{{ app.title }}</h3>
          <span class="badge accent">{{ emuName(app.emulator) }}</span>
        </div>
        <div class="muted small mono" style="margin-top:4px;word-break:break-all">{{ app.image }}</div>
        <div v-if="app.rom_dir" class="muted small mono">📁 {{ app.rom_dir }}</div>
        <div class="row" style="margin-top:6px">
          <span v-if="imagePresent(app) === false" class="badge bad">image absente</span>
          <span v-if="app.runner_type !== 'docker'" class="badge warn">{{ app.runner_type }}</span>
        </div>
        <div v-if="app.notes" class="small muted" style="margin-top:6px">{{ app.notes }}</div>
      </div>
      <div class="row between" style="margin-top:10px">
        <div class="row" style="gap:2px">
          <button class="ghost sm" :disabled="app.index === 0" title="Monter" @click="move(app, -1)">◀</button>
          <button class="ghost sm" :disabled="app.index === profile.apps.length - 1" title="Descendre" @click="move(app, 1)">▶</button>
        </div>
        <div class="row" style="gap:4px">
          <button class="sm" :disabled="app.runner_type !== 'docker'" @click="editing = app">✏️ Configurer</button>
          <button class="sm danger" title="Supprimer" @click="remove(app)">🗑</button>
        </div>
      </div>
    </div>
    <div v-if="!profile.apps.length" class="empty card">Aucune application dans ce profil.</div>
  </div>

  <AppEditor v-if="editing !== undefined" :app="editing" :profile-id="current" :emulators="emulators"
             :base-create-json="baseCreateJson" :sessions="sessions"
             @close="editing = undefined" @saved="saved" />
</template>
