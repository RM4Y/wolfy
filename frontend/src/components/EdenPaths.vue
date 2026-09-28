<script setup>
// Switch (Eden): keys and firmware (uploads), users, ROM folders; paths in "Avancé".
import { computed, onMounted, ref, watch } from 'vue'
import { act, api, toast, upload } from '../api'
import FolderPicker from './FolderPicker.vue'

const emit = defineEmits(['close'])
const saved = ref(null)
const form = ref(null)
const status = ref(null)
const defaults = ref({})
const picking = ref(null) // { field, index? }
const advanced = ref(false)
const progress = ref({}) // keys|firmware -> 0..1
let checkTimer

const PATHS = [
  { id: 'keys', label: 'Clés' },
  { id: 'firmware', label: 'NAND (firmware)' },
  { id: 'users', label: 'Utilisateurs (profils + sauvegardes)' },
]

const dirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(saved.value))
const custom = computed(() => form.value && PATHS.some(p => form.value[p.id] !== defaults.value[p.id]))

async function load() {
  const r = await api.get('/emulators/eden/paths')
  saved.value = r.paths
  form.value = structuredClone(r.paths)
  status.value = r.status
  defaults.value = r.defaults
  if (custom.value) advanced.value = true
}

watch(form, () => {
  clearTimeout(checkTimer)
  checkTimer = setTimeout(async () => {
    try { status.value = (await api.post('/emulators/eden/paths/check', form.value)).status } catch { /* ignore */ }
  }, 400)
}, { deep: true })

async function send(kind, files) {
  if (!files?.length) return
  if (dirty.value) return toast('Enregistre d\'abord les chemins modifiés', 'error')
  if (kind === 'firmware' && !confirm('Remplacer le firmware installé ? L\'actuel est gardé en sauvegarde (registered.bak).')) return
  const fd = new FormData()
  if (kind === 'keys') for (const f of files) fd.append('files', f, f.name)
  else fd.append('file', files[0], files[0].name)
  progress.value = { ...progress.value, [kind]: 0 }
  try {
    const r = await upload(`/emulators/eden/${kind}`, fd, p => (progress.value = { ...progress.value, [kind]: p }))
    status.value = r.status
    toast(kind === 'keys' ? `Clés installées : ${r.installed.join(', ')}`
      : `Firmware installé (${r.installed} fichiers) — version affichée au prochain lancement d'Eden`)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    const p = { ...progress.value }; delete p[kind]; progress.value = p
  }
}

function pick(path) {
  const p = picking.value
  if (p.field === 'roms') {
    if (p.index === undefined) form.value.roms.push(path)
    else form.value.roms[p.index] = path
  } else form.value[p.field] = path
  picking.value = null
}

async function save() {
  const r = await act('Enregistrement des chemins', () => api.put('/emulators/eden/paths', form.value))
  if (!r) return
  const parts = []
  if (r.eden_config_changed) parts.push('config Eden mise à jour')
  if (r.apps_updated.length) parts.push(`montages de ${r.apps_updated.join(', ')} mis à jour (Wolf redémarré)`)
  toast(parts.length ? `Chemins enregistrés : ${parts.join(' · ')}` : 'Aucun changement')
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
        <h2 style="margin:0">🎮 Switch (Eden) — clés, firmware, jeux</h2>
        <button type="button" class="ghost sm" @click="emit('close')">✖</button>
      </div>

      <template v-if="form">
        <div class="grid cols-3" style="gap:12px">
          <div class="card box">
            <h3>🔑 Clés</h3>
            <span class="badge" :class="badge(status?.keys).cls">{{ badge(status?.keys).text }}</span>
            <p class="muted small">prod.keys et title.keys (ou un .zip les contenant).</p>
            <label class="btn sm" :class="{ disabled: progress.keys !== undefined }">
              ⬆ Envoyer les clés
              <input type="file" multiple accept=".keys,.zip" hidden @change="send('keys', $event.target.files); $event.target.value = ''" />
            </label>
            <progress v-if="progress.keys !== undefined" :value="progress.keys" max="1"></progress>
          </div>

          <div class="card box">
            <h3>💾 Firmware</h3>
            <span class="badge" :class="badge(status?.firmware).cls">{{ badge(status?.firmware).text }}</span>
            <p class="muted small">Archive .zip du firmware (fichiers .nca). Remplace l'actuel, gardé en sauvegarde.</p>
            <label class="btn sm" :class="{ disabled: progress.firmware !== undefined }">
              ⬆ Installer un firmware
              <input type="file" accept=".zip" hidden @change="send('firmware', $event.target.files); $event.target.value = ''" />
            </label>
            <template v-if="progress.firmware !== undefined">
              <progress :value="progress.firmware" max="1"></progress>
              <span class="small muted">{{ progress.firmware < 1 ? `envoi ${Math.round(progress.firmware * 100)} %` : 'installation…' }}</span>
            </template>
          </div>

          <div class="card box">
            <h3>👤 Utilisateurs</h3>
            <span class="badge" :class="badge(status?.users).cls">{{ badge(status?.users).text }}</span>
            <p class="muted small">Profils et sauvegardes, partagés par toutes les sessions et Eden sur le PC.</p>
          </div>
        </div>

        <div class="field" style="margin-top:18px">
          <label>🎮 Dossiers de jeux (ROMs)</label>
          <div v-for="(d, i) in form.roms" :key="i" style="margin-bottom:8px">
            <div class="row" style="flex-wrap:nowrap">
              <input v-model="form.roms[i]" class="mono" />
              <button type="button" class="sm" title="Parcourir" @click="picking = { field: 'roms', index: i }">📂</button>
              <button type="button" class="ghost sm danger" title="Retirer" @click="form.roms.splice(i, 1)">✖</button>
            </div>
            <span class="badge" style="margin-top:4px" :class="badge(status?.roms?.[i]).cls">{{ badge(status?.roms?.[i]).text }}</span>
          </div>
          <button type="button" class="sm" @click="picking = { field: 'roms' }">＋ Ajouter un dossier</button>
          <div class="help">Listés dans le menu HOME, montés en lecture seule dans les sessions.</div>
        </div>

        <button type="button" class="ghost sm" @click="advanced = !advanced">{{ advanced ? '▾' : '▸' }} Avancé : emplacements</button>
        <div v-if="advanced" style="margin-top:10px">
          <div v-for="p in PATHS" :key="p.id" class="field">
            <label>{{ p.label }}</label>
            <div class="row" style="flex-wrap:nowrap">
              <input v-model="form[p.id]" class="mono small" />
              <button type="button" class="sm" title="Parcourir" @click="picking = { field: p.id }">📂</button>
              <button v-if="form[p.id] !== defaults[p.id]" type="button" class="ghost sm" title="Emplacement Wolfy"
                      @click="form[p.id] = defaults[p.id]">↺</button>
            </div>
          </div>
          <div class="help">Par défaut dans le projet : <code>config/switch/keys</code>, <code>nand</code>, <code>users</code>.</div>
        </div>

        <div class="row end" style="margin-top:16px">
          <button type="button" class="ghost" @click="emit('close')">Fermer</button>
          <button type="button" class="primary" :disabled="!dirty" @click="save">💾 Enregistrer</button>
        </div>
      </template>
      <div v-else class="empty"><div class="spinner" style="margin:auto"></div></div>
    </div>
  </div>

  <FolderPicker v-if="picking" :start="picking.field === 'roms' ? (form.roms[picking.index] || '/mnt/Jeux/ROMS') : form[picking.field]"
                @pick="pick" @close="picking = null" />
</template>

<style scoped>
.box { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; background: var(--card-2); }
.box h3 { margin: 0; }
.box p { margin: 0; }
.btn.disabled { pointer-events: none; opacity: .5; }
progress { width: 100%; accent-color: var(--accent); }
</style>
