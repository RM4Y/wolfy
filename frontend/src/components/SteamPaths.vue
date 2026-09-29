<script setup>
// Steam: shared data (account) status and library folders.
import { computed, onMounted, ref, watch } from 'vue'
import { act, api, toast } from '../api'
import FolderPicker from './FolderPicker.vue'

const emit = defineEmits(['close'])
const saved = ref(null)
const libs = ref(null)
const status = ref(null)
const dataPath = ref('')
const picking = ref(null)
let checkTimer

const dirty = computed(() => JSON.stringify(libs.value) !== JSON.stringify(saved.value))

async function load() {
  const r = await api.get('/emulators/steam/paths')
  saved.value = r.paths.libraries
  libs.value = [...r.paths.libraries]
  dataPath.value = r.paths.data
  status.value = r.status
}

watch(libs, () => {
  clearTimeout(checkTimer)
  checkTimer = setTimeout(async () => {
    try { status.value = (await api.post('/emulators/steam/paths/check', { libraries: libs.value })).status } catch { /* ignore */ }
  }, 400)
}, { deep: true })

function pick(path) {
  if (picking.value.index === undefined) libs.value.push(path)
  else libs.value[picking.value.index] = path
  picking.value = null
}

async function save() {
  const r = await act('Enregistrement des bibliothèques', () => api.put('/emulators/steam/paths', { libraries: libs.value }))
  if (!r) return
  toast(r.apps_updated.length ? `Bibliothèques enregistrées — montages de ${r.apps_updated.join(', ')} mis à jour (Wolf redémarré)`
    : 'Bibliothèques enregistrées — prises en compte à la prochaine session')
  await load()
}

function badge(s) {
  if (!s) return { cls: '', text: '…' }
  if (!s.exists) return { cls: 'bad', text: 'introuvable' }
  return { cls: s.ok ? 'ok' : 'warn', text: s.detail }
}

onMounted(load)
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <div class="modal">
      <div class="row between" style="margin-bottom:14px">
        <h2 style="margin:0">🎮 Steam — bibliothèques et compte</h2>
        <button type="button" class="ghost sm" @click="emit('close')">✖</button>
      </div>

      <template v-if="libs">
        <div class="card box" style="margin-bottom:16px">
          <h3>👤 Données Steam partagées</h3>
          <span class="badge" :class="badge(status?.data).cls">{{ badge(status?.data).text }}</span>
          <p class="muted small">
            <code>{{ dataPath }}</code> : installation de Steam, connexion au compte et réglages, communs à tous les
            appareils. Steam ne peut tourner que dans une session à la fois : une deuxième session Steam est refusée.
          </p>
        </div>

        <div class="field">
          <label>📚 Bibliothèques Steam (SteamLibrary)</label>
          <div v-for="(d, i) in libs" :key="i" style="margin-bottom:8px">
            <div class="row" style="flex-wrap:nowrap">
              <input v-model="libs[i]" class="mono" />
              <button type="button" class="sm" title="Parcourir" @click="picking = { index: i }">📂</button>
              <button type="button" class="ghost sm danger" title="Retirer" @click="libs.splice(i, 1)">✖</button>
            </div>
            <span class="badge" style="margin-top:4px" :class="badge(status?.libraries?.[i]).cls">{{ badge(status?.libraries?.[i]).text }}</span>
          </div>
          <button type="button" class="sm" @click="picking = {}">＋ Ajouter une bibliothèque</button>
          <div class="help">
            Dossier contenant <code>steamapps</code>. Monté dans les sessions (Steam peut y installer et mettre à jour
            les jeux) et ajouté automatiquement aux bibliothèques de Steam au démarrage.
          </div>
        </div>

        <div class="alert warn small" style="margin:6px 0 14px">
          Une bibliothèque est partagée avec le Steam du PC : évite de lancer Steam sur le PC et dans une session en même
          temps (les deux mettraient à jour les mêmes jeux). Changer les bibliothèques redémarre Wolf.
        </div>
        <div class="row end">
          <button type="button" class="ghost" @click="emit('close')">Fermer</button>
          <button type="button" class="primary" :disabled="!dirty" @click="save">💾 Enregistrer</button>
        </div>
      </template>
      <div v-else class="empty"><div class="spinner" style="margin:auto"></div></div>
    </div>
  </div>

  <FolderPicker v-if="picking" :start="picking.index !== undefined ? libs[picking.index] : '/mnt/Jeux'"
                @pick="pick" @close="picking = null" />
</template>

<style scoped>
.box { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; background: var(--card-2); }
.box h3, .box p { margin: 0; }
</style>
