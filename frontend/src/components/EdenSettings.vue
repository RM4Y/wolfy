<script setup>
// Every setting of Eden's qt-config.ini, grouped in tabs, with a draft of pending changes.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { act, api, toast } from '../api'
import SettingField from './SettingField.vue'
import WolfyEden from './WolfyEden.vue'

const data = ref(null)
const error = ref('')
const tab = ref('wolfy')
const search = ref('')
const draft = ref({}) // "section\0key" -> { value } | { reset: true }

const id = it => `${it.section}\u0000${it.key}`

async function load() {
  try {
    data.value = await api.get('/emulator-settings/eden')
    draft.value = {}
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

const counts = computed(() => {
  const c = {}
  for (const it of data.value?.items || []) c[it.tab] = (c[it.tab] || 0) + 1
  return c
})

const visible = computed(() => {
  if (!data.value) return []
  const q = search.value.trim().toLowerCase()
  return data.value.items.filter(it => q
    ? `${it.label} ${it.key} ${it.help || ''} ${it.section}`.toLowerCase().includes(q)
    : it.tab === tab.value)
})

// groups inside a tab: Eden category, or player/shortcut name
const groups = computed(() => {
  const out = []
  const byName = {}
  for (const it of visible.value) {
    const name = search.value ? (tabLabel(it.tab)) : (it.group || it.category_label || `[${it.section}]`)
    if (!byName[name]) { byName[name] = { name, items: [] }; out.push(byName[name]) }
    byName[name].items.push(it)
  }
  return out
})

const tabLabel = t => data.value?.tabs.find(x => x.id === t)?.label || t

function valueOf(it) {
  const d = draft.value[id(it)]
  if (!d) return it.value
  return d.reset ? it.default : d.value
}

function update(it, v) {
  const d = { ...draft.value }
  if (v === it.value) delete d[id(it)]
  else d[id(it)] = it.type === 'raw' ? { raw: v, value: v } : { value: v }
  draft.value = d
}

function reset(it) {
  draft.value = { ...draft.value, [id(it)]: { reset: true } }
}

const pending = computed(() => Object.keys(draft.value).length)

async function save() {
  const changes = Object.entries(draft.value).map(([k, d]) => {
    const [section, key] = k.split('\u0000')
    return d.reset ? { section, key, reset: true } : d.raw !== undefined ? { section, key, raw: d.raw } : { section, key, value: d.value }
  })
  const r = await act('Enregistrement de la configuration Eden',
    () => api.put('/emulator-settings/eden', { changes, mtime: data.value.mtime }))
  if (r) {
    toast(`${r.changed} réglage(s) enregistré(s) — actif à la prochaine session`)
    load()
  }
}

async function restore(name) {
  if (!name) return
  if (!confirm(`Restaurer la configuration Eden du ${name.replace('qt-config.ini.', '')} ?`)) return
  await act('Restauration', () => api.post(`/emulator-settings/eden/backups/${name}/restore`), 'Configuration restaurée')
  load()
}

function beforeUnload(e) { if (pending.value) { e.preventDefault(); e.returnValue = '' } }
onMounted(() => { load(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
defineExpose({ pending })
</script>

<template>
  <div v-if="error" class="alert bad">{{ error }}</div>
  <template v-if="data">
    <div class="alert info small" style="margin-bottom:16px">
      Configuration Eden <b>partagée</b> (<code>{{ data.path }}</code>) : utilisée par Eden sur le PC et copiée
      au démarrage de <b>chaque session Wolf</b>. Les changements s'appliquent aux prochaines sessions.
      Réglages et libellés issus d'Eden {{ data.eden_tag }}.
    </div>

    <div class="row" style="margin-bottom:14px">
      <input v-model="search" placeholder="🔍 Rechercher un réglage (résolution, vsync, langue…)" style="flex:1;min-width:220px" />
      <select style="width:auto" @change="restore($event.target.value); $event.target.value = ''">
        <option value="">↺ Restaurer une sauvegarde…</option>
        <option v-for="b in data.backups" :key="b.name" :value="b.name">{{ b.name.replace('qt-config.ini.', '') }}</option>
      </select>
    </div>

    <div v-if="!search" class="tabs">
      <button type="button" :class="{ active: tab === 'wolfy' }" @click="tab = 'wolfy'">🐺 Wolfy-Eden</button>
      <button v-for="t in data.tabs" :key="t.id" type="button" :class="{ active: tab === t.id }" @click="tab = t.id">
        {{ t.label }} <span class="muted small">{{ counts[t.id] || 0 }}</span>
      </button>
    </div>
    <div v-else class="muted small" style="margin-bottom:10px">{{ visible.length }} résultat(s)</div>

    <div v-if="tab === 'raw' && !search" class="alert warn small" style="margin-bottom:12px">
      Valeurs brutes du fichier (liaisons de boutons, listes, chemins…) : modifie seulement si tu sais ce que tu fais.
    </div>

    <WolfyEden v-if="tab === 'wolfy' && !search" />

    <div v-for="g in groups" :key="g.name" class="card" style="padding:8px 4px;margin-bottom:14px">
      <h3 style="padding:8px 14px 4px;color:var(--accent-2)">{{ g.name }}</h3>
      <SettingField v-for="it in g.items" :key="id(it)" :item="it" :value="valueOf(it)"
                    :modified="!!draft[id(it)]" @update="v => update(it, v)" @reset="reset(it)" />
    </div>
    <div v-if="!groups.length && (tab !== 'wolfy' || search)" class="empty card">Aucun réglage.</div>

    <div v-if="pending" class="savebar">
      <span><b>{{ pending }}</b> modification(s) non enregistrée(s)</span>
      <div class="row">
        <button type="button" class="ghost" @click="draft = {}">Annuler</button>
        <button type="button" class="primary" @click="save">💾 Enregistrer</button>
      </div>
    </div>
  </template>
  <div v-else-if="!error" class="empty"><div class="spinner" style="margin:auto"></div></div>
</template>

<style scoped>
.savebar {
  position: sticky; bottom: 16px; z-index: 20;
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--card-2); border: 1px solid var(--accent); border-radius: 12px;
  padding: 12px 16px; box-shadow: var(--shadow);
}
</style>
