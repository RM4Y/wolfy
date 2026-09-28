<script setup>
// Switch (Eden) paths: keys, firmware, ROM folders, user saves.
import { computed, onMounted, ref, watch } from 'vue'
import { act, api, toast } from '../api'
import FolderPicker from './FolderPicker.vue'

const emit = defineEmits(['close'])
const saved = ref(null)
const form = ref(null)
const status = ref(null)
const defaults = ref({})
const picking = ref(null) // { field, index? }
let checkTimer

const FIELDS = [
  { id: 'keys', icon: '🔑', label: 'Clés (prod.keys)', help: 'Dossier contenant prod.keys et title.keys.' },
  { id: 'firmware', icon: '💾', label: 'Firmware (NAND)', help: 'NAND d\'Eden : firmware installé, profils et sauvegardes système.' },
  { id: 'users', icon: '👤', label: 'Utilisateurs (sauvegardes)', help: 'Sauvegardes des jeux. Vide = dans la NAND (nand/user/save).' },
]

const dirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(saved.value))

async function load() {
  const r = await api.get('/emulators/eden/paths')
  saved.value = r.paths
  form.value = structuredClone(r.paths)
  status.value = r.status
  defaults.value = r.defaults
}

// re-check the paths as they are typed
watch(form, () => {
  clearTimeout(checkTimer)
  checkTimer = setTimeout(async () => {
    try { status.value = (await api.post('/emulators/eden/paths/check', form.value)).status } catch { /* ignore */ }
  }, 400)
}, { deep: true })

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
      <div class="row between" style="margin-bottom:6px">
        <h2 style="margin:0">📁 Chemins Switch (Eden)</h2>
        <button type="button" class="ghost sm" @click="emit('close')">✖</button>
      </div>
      <p class="muted small" style="margin-top:0">
        Chemins sur le serveur. Ils sont écrits dans la config Eden partagée et montés dans les sessions Wolf
        au même emplacement (les ROMs en lecture seule).
      </p>

      <template v-if="form">
        <div v-for="f in FIELDS" :key="f.id" class="field">
          <label>{{ f.icon }} {{ f.label }}</label>
          <div class="row" style="flex-wrap:nowrap">
            <input v-model="form[f.id]" class="mono" :placeholder="f.id === 'users' ? 'dans la NAND' : defaults[f.id]" />
            <button type="button" class="sm" title="Parcourir" @click="picking = { field: f.id }">📂</button>
            <button v-if="f.id === 'users' && form.users" type="button" class="ghost sm" title="Revenir à la NAND"
                    @click="form.users = ''">✖</button>
          </div>
          <div class="row" style="margin-top:4px">
            <span class="badge" :class="badge(status?.[f.id]).cls">{{ badge(status?.[f.id]).text }}</span>
            <span class="help" style="margin:0">{{ f.help }}</span>
          </div>
        </div>

        <div class="field">
          <label>🎮 ROMs (dossiers de jeux)</label>
          <div v-for="(d, i) in form.roms" :key="i" style="margin-bottom:8px">
            <div class="row" style="flex-wrap:nowrap">
              <input v-model="form.roms[i]" class="mono" />
              <button type="button" class="sm" title="Parcourir" @click="picking = { field: 'roms', index: i }">📂</button>
              <button type="button" class="ghost sm danger" title="Retirer" @click="form.roms.splice(i, 1)">✖</button>
            </div>
            <span class="badge" style="margin-top:4px" :class="badge(status?.roms?.[i]).cls">{{ badge(status?.roms?.[i]).text }}</span>
          </div>
          <button type="button" class="sm" @click="picking = { field: 'roms' }">＋ Ajouter un dossier</button>
          <div class="help">Listés dans Eden (et donc dans le menu HOME) et montés en lecture seule dans les sessions.</div>
        </div>

        <div class="alert warn small" style="margin:6px 0 14px">
          Si les montages changent, Wolf redémarre (les sessions en cours sont coupées). Les clés d'un autre dossier
          ne s'appliquent qu'aux sessions Wolf : Eden sur le PC lit toujours <code>{{ defaults.keys }}</code>.
        </div>
        <div class="row end">
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
