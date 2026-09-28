<script setup>
// Configuration page of one application: emulator settings + Wolf container settings.
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, coverUrl } from '../api'
import AppEditor from '../components/AppEditor.vue'
import EmulatorSettings from '../components/EmulatorSettings.vue'

const route = useRoute()
const router = useRouter()
const app = ref(null)
const emulators = ref([])
const baseCreateJson = ref('')
const sessions = ref(0)
const editContainer = ref(false)
const error = ref('')

const emu = computed(() => emulators.value.find(e => e.id === app.value?.emulator))
const settingsPage = computed(() => emu.value?.settings_page)

async function load() {
  try {
    const [p, e, o] = await Promise.all([api.get('/profiles'), api.get('/emulators'), api.get('/overview')])
    const prof = p.profiles.find(x => x.id === route.params.profile)
    app.value = prof?.apps[Number(route.params.index)] || null
    if (!app.value) error.value = 'Application introuvable'
    emulators.value = e.emulators
    baseCreateJson.value = e.base_create_json
    sessions.value = o.sessions.length
  } catch (err) {
    error.value = err.message
  }
}

function saved() {
  editContainer.value = false
  load()
}

onMounted(load)
</script>

<template>
  <div class="page-head">
    <button class="ghost sm" @click="router.push('/applications')">← Applications</button>
  </div>
  <div v-if="error" class="alert bad">{{ error }}</div>

  <template v-if="app">
    <div class="card row" style="flex-wrap:nowrap;gap:18px;margin-bottom:18px">
      <div style="width:84px;flex:none">
        <img v-if="app.icon" :src="coverUrl(app.icon)" class="cover" alt="" />
        <div v-else class="cover placeholder">🎮</div>
      </div>
      <div style="flex:1;min-width:0">
        <h1>{{ app.title }}</h1>
        <div class="row" style="margin-top:6px">
          <span class="badge accent">{{ emu?.name || app.emulator }}</span>
          <span v-for="s in emu?.systems || []" :key="s" class="badge">{{ s }}</span>
          <span class="badge mono">{{ app.image }}</span>
        </div>
        <div v-if="app.rom_dir" class="muted small mono" style="margin-top:6px">📁 {{ app.rom_dir }}</div>
      </div>
      <button @click="editContainer = true">🐳 Conteneur Wolf</button>
    </div>

    <EmulatorSettings v-if="settingsPage" :key="settingsPage" :emulator="settingsPage" />
    <div v-else class="card empty">
      <div class="big">🧩</div>
      Pas encore de page de réglages pour {{ emu?.name || 'cet émulateur' }}.<br />
      <button class="primary" style="margin-top:12px" @click="editContainer = true">Configurer le conteneur Wolf</button>
    </div>
  </template>

  <AppEditor v-if="editContainer && app" :app="app" :profile-id="route.params.profile" :emulators="emulators"
             :base-create-json="baseCreateJson" :sessions="sessions"
             @close="editContainer = false" @saved="saved" />
</template>
