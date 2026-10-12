<script setup>
// Configuration page of one application: emulator settings + Wolf container settings.
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import AppEditor from '../components/AppEditor.vue'
import EmulatorSettings from '../components/EmulatorSettings.vue'
import Cover from '../components/Cover.vue'

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
    <button class="ghost sm" @click="router.push('/applications')"><Icon name="arrow-left" />Applications</button>
  </div>
  <div v-if="error" class="alert bad"><Icon name="alert" /><div>{{ error }}</div></div>

  <template v-if="app">
    <div class="card row app-head">
      <Cover :app="app" :label="false" class="app-thumb" />
      <div style="flex:1;min-width:0">
        <h1>{{ app.title }}</h1>
        <div class="row" style="margin-top:6px">
          <span class="badge accent">{{ emu?.name || app.emulator }}</span>
          <span v-for="s in emu?.systems || []" :key="s" class="badge">{{ s }}</span>
          <span class="badge mono">{{ app.image }}</span>
        </div>
        <div v-if="app.rom_dir" class="muted mono row" style="margin-top:6px;gap:6px"><Icon name="folder" class="sm" />{{ app.rom_dir }}</div>
      </div>
      <button @click="editContainer = true"><Icon name="box" />Conteneur Wolf</button>
    </div>

    <EmulatorSettings v-if="settingsPage" :key="settingsPage" :emulator="settingsPage" />
    <div v-else class="card empty">
      <div class="icon"><Icon name="layers" /></div>
      <div class="title">Pas encore de page de réglages pour {{ emu?.name || 'cet émulateur' }}</div>
      <button style="margin-top:8px" @click="editContainer = true"><Icon name="box" />Configurer le conteneur Wolf</button>
    </div>
  </template>

  <AppEditor v-if="editContainer && app" :app="app" :profile-id="route.params.profile" :emulators="emulators"
             :base-create-json="baseCreateJson" :sessions="sessions"
             @close="editContainer = false" @saved="saved" />
</template>

<style scoped>
.app-head { flex-wrap: nowrap; gap: var(--space-4); padding: var(--space-4); margin-bottom: var(--space-5); }
.app-thumb { width: 88px; aspect-ratio: 1; flex: none; border-radius: var(--radius-lg); padding: 10px; }
.app-thumb :deep(.glyph) { font-size: 80px; top: -8px; }
@media (max-width: 600px) { .app-head { flex-wrap: wrap; } .app-thumb { width: 64px; } }
</style>
