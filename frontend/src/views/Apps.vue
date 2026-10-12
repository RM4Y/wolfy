<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { act, api } from '../api'
import AppEditor from '../components/AppEditor.vue'
import Cover from '../components/Cover.vue'

const profiles = ref([])
const current = ref('')
const emulators = ref([])
const baseCreateJson = ref('')
const sessions = ref(0)
const editing = ref(undefined) // undefined = closed, null = new app
const error = ref('')
const router = useRouter()

const profile = computed(() => profiles.value.find(p => p.id === current.value))
const emuName = id => emulators.value.find(e => e.id === id)?.name || id

async function load() {
  try {
    const [p, e, o] = await Promise.all([api.get('/profiles'), api.get('/emulators'), api.get('/overview')])
    profiles.value = p.profiles
    emulators.value = e.emulators
    baseCreateJson.value = e.base_create_json
    sessions.value = o.sessions.length
    current.value = p.profiles.find(x => x.moonlight)?.id || ''
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

// reorder by dragging the handle (desktop); the arrows stay for touch screens
const dragging = ref(null)
const over = ref(null)
function dragStart(app, ev) {
  dragging.value = app
  ev.dataTransfer.effectAllowed = 'move'
  ev.dataTransfer.setData('text/plain', String(app.index))
}
function dragEnd() { dragging.value = over.value = null }
function drop(target) {
  const from = dragging.value
  dragging.value = over.value = null
  if (from && from.index !== target.index) move(from, target.index - from.index)
}

function saved() {
  editing.value = undefined
  load()
}

onMounted(load)
</script>

<template>
  <div class="page-head">
    <div>
      <h1>Applications</h1>
      <div v-if="profile" class="sub">{{ profile.apps.length }} application(s) visibles dans Moonlight · glisser la poignée pour réordonner</div>
    </div>
    <div class="spacer"></div>
    <button class="primary" @click="editing = null"><Icon name="plus" />Nouvelle application</button>
  </div>
  <div v-if="error" class="alert bad" style="margin-bottom:16px"><Icon name="alert" /><div>{{ error }}</div></div>

  <div v-if="profile && profile.apps.length" class="apps">
    <article v-for="app in profile.apps" :key="app.index + app.title" class="card app"
             :class="{ dragging: dragging === app, over: over === app && dragging !== app }"
             @dragover.prevent="over = app" @dragleave="over === app && (over = null)" @drop.prevent="drop(app)">
      <Cover :app="app" class="app-cover" />
      <div class="app-body">
        <div class="row between" style="gap:8px;flex-wrap:nowrap">
          <span class="app-name">{{ app.title }}</span>
          <span class="badge accent">{{ emuName(app.emulator) }}</span>
        </div>
        <span class="muted mono" style="word-break:break-all">{{ app.image }}</span>
        <span v-if="app.rom_dir" class="muted mono row" style="gap:6px;flex-wrap:nowrap"><Icon name="folder" class="sm" />{{ app.rom_dir }}</span>
        <div v-if="imagePresent(app) === false || app.runner_type !== 'docker'" class="row" style="gap:6px">
          <span v-if="imagePresent(app) === false" class="badge bad">Image absente</span>
          <span v-if="app.runner_type !== 'docker'" class="badge warn">{{ app.runner_type }}</span>
        </div>
        <div v-if="app.notes" class="small muted">{{ app.notes }}</div>
      </div>
      <div class="app-foot">
        <span class="handle" draggable="true" title="Glisser pour réordonner"
              @dragstart="dragStart(app, $event)" @dragend="dragEnd"><Icon name="grip" /></span>
        <button class="ghost sm icon touch" :disabled="app.index === 0" aria-label="Monter" @click="move(app, -1)"><Icon name="chevron-left" /></button>
        <button class="ghost sm icon touch" :disabled="app.index === profile.apps.length - 1" aria-label="Descendre" @click="move(app, 1)"><Icon name="chevron-right" /></button>
        <span style="flex:1"></span>
        <button class="sm" :disabled="app.runner_type !== 'docker'"
                @click="router.push(`/applications/${current}/${app.index}`)"><Icon name="sliders" />Configurer</button>
        <button class="ghost sm icon" aria-label="Supprimer" title="Supprimer" @click="remove(app)"><Icon name="trash" /></button>
      </div>
    </article>
  </div>
  <div v-else-if="profile" class="card empty">
    <div class="icon"><Icon name="gamepad" /></div>
    <div class="title">Aucune application</div>
    <div class="text">Ajoute une application pour la voir dans Moonlight.</div>
  </div>

  <AppEditor v-if="editing !== undefined" :app="editing" :profile-id="current" :emulators="emulators"
             :base-create-json="baseCreateJson" :sessions="sessions"
             @close="editing = undefined" @saved="saved" />
</template>

<style scoped>
.apps { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--space-6); }
.app { padding: 0; overflow: hidden; display: flex; flex-direction: column; transition: transform .18s, box-shadow .18s, opacity .18s; }
.app:hover { transform: translateY(-2px); box-shadow: var(--shadow-card), 0 0 40px -14px var(--glow-brand); }
.app.dragging { opacity: .45; }
.app.over { box-shadow: 0 0 0 2px var(--brand), var(--shadow-glow); }
.app-cover { aspect-ratio: 4 / 3; margin: 8px 8px 0; }
.app-body { flex: 1; padding: var(--space-4); display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.app-name { font-weight: 600; font-size: 15px; }
.app-foot { display: flex; align-items: center; gap: var(--space-1); padding: 0 var(--space-4) var(--space-4); }
.handle { color: var(--ink-faint); cursor: grab; display: grid; place-items: center; width: 28px; height: 30px; border-radius: var(--radius-sm); }
.handle:hover { background: var(--surface-raised); color: var(--ink); }
.touch { display: none; }
@media (hover: none) { .handle { display: none; } .touch { display: inline-flex; } }
</style>
