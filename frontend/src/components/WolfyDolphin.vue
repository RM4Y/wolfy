<script setup>
// "Wolfy-Dolphin" tab: settings specific to the Wii sessions (players: Wolf pads, gamepads
// plugged into the PC, real Wii Remotes).
import { computed, onMounted, ref } from 'vue'
import { act, api, toast } from '../api'
import HomeCombo from './HomeCombo.vue'

const SOURCES = [
  { value: 'pad', label: '🎮 Manette Moonlight', help: 'Wiimote simulée sur la manette de l\'appareil Moonlight (Xbox : pointeur au stick droit)' },
  { value: 'host', label: '🕹️ Manette du PC', help: 'Manette branchée sur le serveur (USB ou Bluetooth), Wiimote simulée' },
  { value: 'real', label: '📡 Vraie Wiimote', help: 'Wiimote connectée au Bluetooth du serveur (1 + 2 pour l\'appairer)' },
  { value: 'none', label: '⛔ Aucune', help: 'Emplacement vide' },
]
const saved = ref(null)
const form = ref(null)
const pads = ref(null)      // gamepads detected on the PC
const detecting = ref(false)
const dirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(saved.value))
const clone = v => JSON.parse(JSON.stringify(v))

async function load() {
  saved.value = await api.get('/emulator-settings/dolphin/wolfy')
  form.value = clone(saved.value)
  if (form.value.wiimotes.includes('host')) detect()
}

async function detect() {
  detecting.value = true
  try { pads.value = (await api.get('/emulator-settings/dolphin/host-pads')).pads }
  catch (e) { toast(e.message, 'error') }
  finally { detecting.value = false }
}

const padKey = p => p ? `${p.vendor}:${p.product}:${p.uniq || ''}:${p.name}` : ''
// detected pads + the chosen one if it is not plugged in right now
function choices(i) {
  const list = [...(pads.value || [])]
  const cur = form.value.host_pads[i]
  if (cur && !list.some(p => padKey(p) === padKey(cur))) list.push({ ...cur, missing: true })
  return list
}
function choosePad(i, key) {
  form.value.host_pads[i] = choices(i).find(p => padKey(p) === key) || null
  if (form.value.host_pads[i]) delete form.value.host_pads[i].missing
}
function setSource(i, value) {
  form.value.wiimotes[i] = value
  if (value === 'host' && pads.value === null) detect()
}

async function save() {
  const r = await act('Enregistrement', () => api.put('/emulator-settings/dolphin/wolfy', form.value),
    'Manettes enregistrées — actives à la prochaine session')
  if (r) { saved.value = r; form.value = clone(r) }
}

// the n-th "pad" slot uses the n-th Moonlight pad of the session
const padIndex = i => form.value.wiimotes.slice(0, i + 1).filter(s => s === 'pad').length
const padLabel = p => `${p.sdl_name}${p.name && p.name !== p.sdl_name ? ` — ${p.name}` : ''}${p.uniq ? ` (${p.uniq})` : ''}${p.missing ? ' · non branchée' : ''}`

onMounted(load)
</script>

<template>
  <HomeCombo emulator="dolphin" />

  <div v-if="form" class="card">
    <h2 style="margin:0">🎯 Joueurs</h2>
    <div class="muted small" style="margin-bottom:14px">
      Chaque joueur Wii (et le port GameCube du même numéro) est la manette d'un appareil Moonlight, une manette
      branchée sur le PC, ou une vraie Wiimote connectée au Bluetooth du serveur. Une manette ou une Wiimote
      éteinte ne compte pas comme connectée ; une manette du PC allumée pendant la session est reconnue.
    </div>
    <div v-for="(slot, i) in form.wiimotes" :key="i" style="margin-bottom:12px">
      <div class="row" style="align-items:center">
        <b style="width:90px">Joueur {{ i + 1 }}</b>
        <div class="row" style="flex:1;gap:6px">
          <button v-for="s in SOURCES" :key="s.value" type="button" class="sm" :class="{ primary: slot === s.value }"
                  :title="s.help" @click="setSource(i, s.value)">{{ s.label }}</button>
        </div>
        <span v-if="slot === 'pad'" class="muted small">manette n° {{ padIndex(i) }} de la session</span>
      </div>
      <div v-if="slot === 'host'" class="row" style="margin:6px 0 0 90px;gap:6px;flex-wrap:nowrap">
        <select :value="padKey(form.host_pads[i])" style="flex:1" @change="choosePad(i, $event.target.value)">
          <option value="">— Choisir une manette du PC —</option>
          <option v-for="p in choices(i)" :key="padKey(p)" :value="padKey(p)">{{ padLabel(p) }}</option>
        </select>
        <button type="button" class="ghost sm" :disabled="detecting" @click="detect">
          {{ detecting ? '…' : '🔄 Détecter' }}
        </button>
      </div>
      <div v-if="slot === 'host' && pads && !pads.length" class="muted small" style="margin:4px 0 0 90px">
        Aucune manette détectée sur le PC : branche-la ou allume-la, puis « Détecter ».
      </div>
    </div>
    <label class="row" style="margin-top:12px;gap:10px;align-items:center">
      <span class="switch"><input v-model="form.nunchuk" type="checkbox" /><span></span></span>
      Nunchuk branché sur les Wiimotes simulées (stick gauche, C = LB, Z = LT)
    </label>
    <div v-if="dirty" class="row end" style="margin-top:12px">
      <button type="button" class="ghost" @click="form = clone(saved)">Annuler</button>
      <button type="button" class="primary" @click="save">💾 Enregistrer</button>
    </div>
  </div>
</template>
