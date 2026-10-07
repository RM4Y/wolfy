<script setup>
// PlayStation (RetroArch): BIOS and firmwares of every console (upload), saves, states, ROM folders,
// PS3 / PS Vita games; paths in "Avancé".
import { computed, onMounted, ref, watch } from 'vue'
import { act, api, toast, upload } from '../api'
import FolderPicker from './FolderPicker.vue'
import JobLog from './JobLog.vue'
import PsStandalone from './PsStandalone.vue'

const emit = defineEmits(['close'])
const saved = ref(null)
const form = ref(null)
const status = ref(null)
const defaults = ref({})
const picking = ref(null)
const advanced = ref(false)
const progress = ref({})  // upload progress per card
const ps = ref(null)      // PS3 / PS Vita: firmwares, games, installables
const jobId = ref('')     // firmware install

// one card per console, in console order: BIOS (RetroArch cores), firmware (standalone
// emulators) or nothing needed
const CARDS = [
  { id: 'ps1', kind: 'bios', title: 'PS1', emu: 'Beetle PSX HW', accept: '.bin,.zip',
    help: 'BIOS .bin de 512 Ko (scph5500 Japon, scph5501 Amérique du Nord, scph5502 Europe), renommé si besoin.' },
  { id: 'ps2', kind: 'bios', title: 'PS2', emu: 'LRPS2', accept: '.bin,.nvm,.mec,.rom1,.rom2,.erom,.zip',
    help: 'BIOS .bin de 4 Mo (+ .nvm / .mec), ou un .zip.' },
  { id: 'ps3', kind: 'firmware', title: 'PS3', emu: 'RPCS3', pup: 'PS3UPDAT.PUP' },
  { id: 'psp', kind: 'none', title: 'PSP', emu: 'PPSSPP' },
  { id: 'vita', kind: 'firmware', title: 'PS Vita', emu: 'Vita3K', pup: 'PSVUPDAT.PUP' },
]

const dirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(saved.value))

async function loadPs() {
  try { ps.value = await api.get('/emulators/retroarch/ps') } catch (e) { toast(e.message, 'error') }
}

async function load() {
  loadPs()
  const r = await api.get('/emulators/retroarch/paths')
  saved.value = r.paths
  form.value = structuredClone(r.paths)
  status.value = r.status
  defaults.value = r.defaults
  if (PATHS.some(p => r.paths[p.id] !== r.defaults[p.id])) advanced.value = true
}

watch(form, () => {
  clearTimeout(checkTimer)
  checkTimer = setTimeout(async () => {
    try { status.value = (await api.post('/emulators/retroarch/paths/check', form.value)).status } catch { /* ignore */ }
  }, 400)
}, { deep: true })

async function sendBios(console, files) {
  if (!files?.length) return
  if (dirty.value) return toast('Enregistre d\'abord les chemins modifiés', 'error')
  const fd = new FormData()
  for (const f of files) fd.append('files', f, f.name)
  progress.value = { ...progress.value, [console]: 0 }
  try {
    const r = await upload(`/emulators/retroarch/bios?console=${console}`, fd,
      p => (progress.value = { ...progress.value, [console]: p }))
    status.value = r.status
    toast(`BIOS installé(s) : ${r.installed.join(', ')}` + (r.ignored.length ? ` — ignoré(s) : ${r.ignored.join(', ')}` : ''))
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    progress.value = { ...progress.value, [console]: null }
  }
}

async function sendFirmware(system, files) {
  if (!files?.length) return
  const fd = new FormData()
  fd.append('file', files[0], files[0].name)
  progress.value = { ...progress.value, [system]: 0 }
  try {
    const r = await upload(`/emulators/retroarch/ps/firmware/${system}`, fd,
      p => (progress.value = { ...progress.value, [system]: p }))
    jobId.value = r.job.id
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    progress.value = { ...progress.value, [system]: null }
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
  const r = await act('Enregistrement des chemins', () => api.put('/emulators/retroarch/paths', form.value))
  if (!r) return
  const parts = []
  if (r.config_changed) parts.push('retroarch.cfg mis à jour')
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
        <h2 style="margin:0">🎮 PlayStation — BIOS et firmwares, jeux, sauvegardes</h2>
        <button type="button" class="ghost sm" @click="emit('close')">✖</button>
      </div>

      <template v-if="form">
        <div v-if="status?.host_retroarch_running" class="alert warn small" style="margin-bottom:12px">
          RetroArch est ouvert sur le PC : ferme-le avant de changer les chemins (il réécrit sa config en quittant).
        </div>

        <h3 style="margin:0 0 10px">💿 BIOS et firmwares</h3>
        <div class="grid cols-3" style="gap:12px">
          <div v-for="c in CARDS" :key="c.id" class="card box">
            <template v-if="c.kind === 'bios'">
              <h3>{{ c.title }} <span class="muted small">· BIOS · {{ c.emu }}</span></h3>
              <span class="badge" :class="badge(status?.[`bios_${c.id}`]).cls">{{ badge(status?.[`bios_${c.id}`]).text }}</span>
              <p class="muted small">{{ c.help }}</p>
              <label class="btn sm" :class="{ disabled: progress[c.id] != null }">
                ⬆ Envoyer le BIOS {{ c.title }}
                <input type="file" multiple :accept="c.accept" hidden
                       @change="sendBios(c.id, $event.target.files); $event.target.value = ''" />
              </label>
            </template>
            <template v-else-if="c.kind === 'firmware'">
              <h3>{{ c.title }} <span class="muted small">· firmware · {{ c.emu }}</span></h3>
              <span v-if="ps" class="badge" :class="ps[c.id].firmware ? 'ok' : 'warn'">
                {{ ps[c.id].firmware ? `Firmware ${ps[c.id].firmware}` : 'manquant' }}
              </span>
              <span v-else class="badge">…</span>
              <p class="muted small">Fichier officiel {{ c.pup }} de Sony, installé dans {{ c.emu }}.</p>
              <label class="btn sm" :class="{ disabled: progress[c.id] != null }">
                ⬆ Envoyer {{ c.pup }}
                <input type="file" accept=".pup,.PUP" hidden @change="sendFirmware(c.id, $event.target.files); $event.target.value = ''" />
              </label>
            </template>
            <template v-else>
              <h3>{{ c.title }} <span class="muted small">· {{ c.emu }}</span></h3>
              <span class="badge ok">aucun BIOS nécessaire</span>
              <p class="muted small">PPSSPP émule le système de la PSP lui-même.</p>
            </template>
            <progress v-if="progress[c.id] != null" :value="progress[c.id]" max="1"></progress>
          </div>
        </div>

        <h3 style="margin:18px 0 10px">💾 Sauvegardes</h3>
        <div class="grid cols-2" style="gap:12px">
          <div class="card box">
            <h3>💾 Sauvegardes</h3>
            <span class="badge" :class="badge(status?.saves).cls">{{ badge(status?.saves).text }}</span>
            <p class="muted small">Memory cards PS1 / PS2, sauvegardes PSP. Partagées par toutes les sessions et RetroArch sur le PC.</p>
          </div>
          <div class="card box">
            <h3>⏱ États</h3>
            <span class="badge" :class="badge(status?.states).cls">{{ badge(status?.states).text }}</span>
            <p class="muted small">Sauvegardes instantanées de RetroArch.</p>
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
          <div class="help">Montés en lecture seule dans les sessions. PS1 / PS2 / PSP : ajoute les jeux dans RetroArch avec
            « Importer du contenu ». PS3 / PS Vita : listés automatiquement dans le XMB.</div>
        </div>

        <h3 style="margin:18px 0 10px">PS3 et PS Vita : jeux</h3>
        <PsStandalone :data="ps" @reload="loadPs" />

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
          <div class="help">Par défaut dans le projet : <code>config/playstation/bios</code>, <code>saves</code>, <code>states</code>.</div>
        </div>

        <div class="row end" style="margin-top:16px">
          <button type="button" class="ghost" @click="emit('close')">Fermer</button>
          <button type="button" class="primary" :disabled="!dirty" @click="save">💾 Enregistrer</button>
        </div>
      </template>
      <div v-else class="empty"><div class="spinner" style="margin:auto"></div></div>
    </div>
  </div>

  <JobLog v-if="jobId" :job-id="jobId" @close="jobId = ''" @done="loadPs" />
  <FolderPicker v-if="picking" :start="picking.field === 'roms' ? (form.roms[picking.index] || defaults.roms?.[0] || '/') : form[picking.field]"
                @pick="pick" @close="picking = null" />
</template>

<style scoped>
.box { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; background: var(--card-2); }
.box h3, .box p { margin: 0; }
.btn.disabled { pointer-events: none; opacity: .5; }
progress { width: 100%; accent-color: var(--accent); }
</style>
