<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { act, api, toast } from '../api'

const emit = defineEmits(['refresh'])
const pending = ref([])
const clients = ref([])
const error = ref('')
const forms = reactive({}) // pair_secret -> { pin, name }
const editing = ref(null)
let timer

async function load() {
  clearTimeout(timer)
  try {
    const r = await api.get('/pairing')
    pending.value = r.pending
    clients.value = r.clients
    for (const p of r.pending) forms[p.pair_secret] ??= { pin: '', name: '' }
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
  timer = setTimeout(load, 3000)
}

async function pair(p) {
  const f = forms[p.pair_secret]
  const r = await act('Appairage', () => api.post('/pairing/pair', {
    pair_secret: p.pair_secret, pin: f.pin, name: f.name, client_ip: p.client_ip || '',
  }))
  if (r) {
    toast(r.client_id ? 'Appareil appairé 🎉' : 'PIN envoyé — vérifie Moonlight')
    delete forms[p.pair_secret]
    load()
    emit('refresh')
  }
}

function edit(c) {
  const s = c.settings || {}
  editing.value = {
    client_id: c.client_id,
    name: c.name,
    controller: s.controllers_override?.[0] || 'AUTO',
    mouse_acceleration: s.mouse_acceleration ?? 1,
    v_scroll_acceleration: s.v_scroll_acceleration ?? 1,
    h_scroll_acceleration: s.h_scroll_acceleration ?? 1,
  }
}

async function saveEdit() {
  const e = editing.value
  const ok = await act('Enregistrement', () => api.patch(`/clients/${e.client_id}`, {
    name: e.name,
    settings: {
      controllers_override: e.controller === 'AUTO' ? [] : [e.controller],
      mouse_acceleration: Number(e.mouse_acceleration),
      v_scroll_acceleration: Number(e.v_scroll_acceleration),
      h_scroll_acceleration: Number(e.h_scroll_acceleration),
    },
  }), 'Appareil mis à jour')
  if (ok) { editing.value = null; load() }
}

async function unpair(c) {
  if (!confirm(`Désappairer « ${c.name || c.client_id} » ? Il faudra refaire l'appairage dans Moonlight.`)) return
  await act('Désappairage', () => api.del(`/clients/${c.client_id}`), 'Appareil désappairé')
  load()
}

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div class="page-head">
    <h1>Appairage</h1>
    <div class="spacer"></div>
  </div>
  <div v-if="error" class="alert bad" style="margin-bottom:16px">{{ error }}</div>

  <div class="card">
    <h2>Demandes en attente</h2>
    <div v-if="!pending.length" class="empty">
      <div class="big">🔑</div>
      Aucune demande. Dans Moonlight, ajoute le PC (IP du serveur) : il affiche un code PIN
      et la demande apparaît ici automatiquement.
    </div>
    <div v-else class="grid cols-2">
      <form v-for="p in pending" :key="p.pair_secret" class="card" style="background:var(--card-2)"
            @submit.prevent="pair(p)">
        <div class="row between" style="margin-bottom:12px">
          <h3>📱 Nouvel appareil</h3>
          <span class="badge mono">{{ p.client_ip || 'IP inconnue' }}</span>
        </div>
        <div class="field">
          <label>Code PIN affiché dans Moonlight</label>
          <input v-model="forms[p.pair_secret].pin" class="pin-input mono" inputmode="numeric"
                 maxlength="4" placeholder="••••" autofocus />
        </div>
        <div class="field">
          <label>Nom de l'appareil (facultatif)</label>
          <input v-model="forms[p.pair_secret].name" placeholder="ex. Steam Deck, TV salon…" />
        </div>
        <button class="primary" :disabled="!/^\d{4}$/.test(forms[p.pair_secret].pin)">✔ Appairer</button>
      </form>
    </div>
  </div>

  <div class="card">
    <h2>Appareils appairés ({{ clients.length }})</h2>
    <div v-if="!clients.length" class="empty">Aucun appareil appairé.</div>
    <div v-else class="table-wrap">
      <table>
        <thead><tr><th>Appareil</th><th>Manette</th><th>Dossier d'état</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in clients" :key="c.client_id">
            <td>
              <b>{{ c.name || 'Sans nom' }}</b>
              <div class="muted small mono">{{ c.client_id }}<span v-if="c.client_ip"> · {{ c.client_ip }}</span></div>
              <div v-if="c.paired_at" class="muted small">appairé le {{ c.paired_at }}</div>
            </td>
            <td><span class="badge">{{ c.settings?.controllers_override?.[0] || 'Auto' }}</span></td>
            <td class="mono small muted">{{ c.app_state_folder }}</td>
            <td style="text-align:right;white-space:nowrap">
              <button class="sm" @click="edit(c)">✏️ Modifier</button>
              <button class="sm danger" @click="unpair(c)">✖</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="editing" class="modal-back" @click.self="editing = null">
    <form class="modal narrow" @submit.prevent="saveEdit">
      <h2>Modifier l'appareil</h2>
      <div class="field">
        <label>Nom</label>
        <input v-model="editing.name" />
      </div>
      <div class="field">
        <label>Type de manette virtuelle</label>
        <select v-model="editing.controller">
          <option value="AUTO">Automatique (selon Moonlight)</option>
          <option value="XBOX">Xbox</option>
          <option value="PS">PlayStation</option>
          <option value="NINTENDO">Nintendo</option>
        </select>
        <div class="help">Les émulateurs sont mappés sur la manette Xbox virtuelle de Wolf : change avec prudence.</div>
      </div>
      <div class="grid" style="grid-template-columns:repeat(3,1fr)">
        <div class="field"><label>Accél. souris</label><input v-model="editing.mouse_acceleration" type="number" step="0.1" min="0.1" /></div>
        <div class="field"><label>Défil. vertical</label><input v-model="editing.v_scroll_acceleration" type="number" step="0.1" min="0.1" /></div>
        <div class="field"><label>Défil. horizontal</label><input v-model="editing.h_scroll_acceleration" type="number" step="0.1" min="0.1" /></div>
      </div>
      <div class="row end">
        <button type="button" class="ghost" @click="editing = null">Annuler</button>
        <button class="primary">Enregistrer</button>
      </div>
    </form>
  </div>
</template>
